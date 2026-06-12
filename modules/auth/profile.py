from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand


def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/profile")
    @login_required
    def api_profile_get():
        me=ctx.get_me()
        sid = None
        sid_raw = (request.args.get("station_id") or "").strip()
        if sid_raw:
            try:
                sid = int(sid_raw)
            except Exception:
                return jsonify({"error":"invalid_station_id"}), 400
            if not ctx.can_access_station(me, sid):
                return jsonify({"error":"forbidden"}), 403
        elif ctx.has_global_station_scope(me):
            sid = None
        else:
            sid = me.get("station_id")
        if not sid:
            return jsonify({"profile": None})
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT * FROM station_profiles WHERE station_id=?", (sid,))
        row=cur.fetchone()
        conn.close()
        return jsonify({"profile": dict(row) if row else None})

    @app.post("/api/profile")
    @login_required
    def api_profile_update():
        me=ctx.get_me()
        if me.get("role") != "admin":
            return jsonify({"error":"forbidden"}),403
        if me["role"]=="admin":
            station_id=int(request.form.get("station_id") or 0)
            if not station_id:
                return jsonify({"error":"station_id_required"}),400
        else:
            station_id=ctx.require_station(me)
        # allow update even if blocked? yes, but sensitive actions will be blocked elsewhere
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT 1 FROM stations WHERE id=?", (station_id,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"error":"station_not_found"}),404
        conn.close()
        permit=request.form.get("permit_number")
        legal=request.form.get("legal_name")
        cer=request.files.get("fiel_cer")
        key=request.files.get("fiel_key")
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
        # FIEL files are small; enforce 10MB
        limit_fiel = min(limit, 10)
        cer_rel = ctx.save_upload_checked(cer, f"stations/{station_id}/fiel", allowed_ext={".cer"}, limit_mb=limit_fiel) if cer else None
        key_rel = ctx.save_upload_checked(key, f"stations/{station_id}/fiel", allowed_ext={".key"}, limit_mb=limit_fiel) if key else None

        # Station private data fields (autofill source for templates)
        private_fields = (
            "rfc", "domicilio", "permiso_cre", "representante_legal",
            "responsable_operativo", "responsable_sasisopa", "responsable_sgm",
            "correo", "telefono",
        )
        private_values = {f: (request.form.get(f) or None) for f in private_fields if f in request.form}

        # Logos (image uploads). Stored under stations/<id>/branding/.
        logo_emp = request.files.get("logo_empresa")
        logo_est = request.files.get("logo_estacion")
        logo_emp_rel = ctx.save_upload_checked(logo_emp, f"stations/{station_id}/branding", allowed_ext={".png", ".jpg", ".jpeg"}, limit_mb=min(limit, 5)) if logo_emp else None
        logo_est_rel = ctx.save_upload_checked(logo_est, f"stations/{station_id}/branding", allowed_ext={".png", ".jpg", ".jpeg"}, limit_mb=min(limit, 5)) if logo_est else None

        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT station_id FROM station_profiles WHERE station_id=?", (station_id,))
        exists=cur.fetchone()
        upd=ctx.now_iso()
        if exists:
            cur.execute(
                "UPDATE station_profiles SET permit_number=COALESCE(?,permit_number), legal_name=COALESCE(?,legal_name), "
                "fiel_cer_path=COALESCE(?,fiel_cer_path), fiel_key_path=COALESCE(?,fiel_key_path), fiel_updated_at=?, "
                "logo_empresa_path=COALESCE(?,logo_empresa_path), logo_estacion_path=COALESCE(?,logo_estacion_path), "
                "updated_at=? "
                "WHERE station_id=?",
                (permit or None, legal or None, cer_rel, key_rel, upd, logo_emp_rel, logo_est_rel, upd, station_id),
            )
            # Update only the private fields the form actually sent (preserves existing values otherwise).
            for col, val in private_values.items():
                cur.execute(f"UPDATE station_profiles SET {col}=? WHERE station_id=?", (val, station_id))
        else:
            cur.execute(
                "INSERT INTO station_profiles (station_id, permit_number, legal_name, fiel_cer_path, fiel_key_path, fiel_updated_at, "
                "logo_empresa_path, logo_estacion_path, rfc, domicilio, permiso_cre, representante_legal, "
                "responsable_operativo, responsable_sasisopa, responsable_sgm, correo, telefono, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    station_id, permit or None, legal or None, cer_rel or "", key_rel or "", upd,
                    logo_emp_rel, logo_est_rel,
                    private_values.get("rfc"), private_values.get("domicilio"), private_values.get("permiso_cre"),
                    private_values.get("representante_legal"), private_values.get("responsable_operativo"),
                    private_values.get("responsable_sasisopa"), private_values.get("responsable_sgm"),
                    private_values.get("correo"), private_values.get("telefono"),
                    upd,
                ),
            )
        conn.commit(); conn.close()
        ctx.log_action(me,"update_station_profile","station_profiles",str(station_id),{"fields_set": sorted(list(private_values.keys()))})
        return jsonify({"ok":True})

    # ---------------- operator dashboard summary ----------------

    @app.get("/api/operator/summary")
    @login_required
    def api_operator_summary():
        """Lightweight stats for operator/jefe dashboards (daily/monthly/yearly + last 30 days).

        Frontend can use this to render charts without heavy queries.
        """
        me = ctx.get_me()
        if me["role"] == "admin":
            return jsonify({"error": "admin_no_station"}), 400
        sid = ctx.require_station(me)

        today = datetime.date.today()
        start_30 = (today - datetime.timedelta(days=29)).isoformat()
        today_str = today.isoformat()
        month_start = today.replace(day=1).isoformat()
        year_start = today.replace(month=1, day=1).isoformat()

        conn = get_conn(); cur = conn.cursor()

        def total_events(d1: str, d2: str):
            cur.execute(
                "SELECT COUNT(*) AS c FROM calendar_events WHERE brand=? AND (station_id IS NULL OR station_id=?) AND date(start_date)>=date(?) AND date(start_date)<=date(?)",
                (get_brand(), sid, d1, d2),
            )
            return int(cur.fetchone()["c"] or 0)

        def approved_events(d1: str, d2: str):
            cur.execute(
                "SELECT COUNT(DISTINCT event_id) AS c FROM submissions WHERE brand=? AND station_id=? AND status<>'rejected' AND date(created_at)>=date(?) AND date(created_at)<=date(?)",
                (get_brand(), sid, d1, d2),
            )
            return int(cur.fetchone()["c"] or 0)

        daily = {"total": total_events(today_str, today_str), "approved": approved_events(today_str, today_str)}
        monthly = {"total": total_events(month_start, today_str), "approved": approved_events(month_start, today_str)}
        yearly = {"total": total_events(year_start, today_str), "approved": approved_events(year_start, today_str)}

        # Series last 30 days
        series = []
        for i in range(30):
            d = (today - datetime.timedelta(days=29 - i)).isoformat()
            series.append({
                "date": d,
                "total": total_events(d, d),
                "approved": approved_events(d, d),
            })

        conn.close()
        return jsonify({"daily": daily, "monthly": monthly, "yearly": yearly, "last_30_days": series})

    # ---------------- notifications ----------------


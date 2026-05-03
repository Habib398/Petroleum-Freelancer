from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand


# Allowed values are enforced at the DB level (CHECK constraint) and used here for validation.
ALLOWED_ALERT_SEV = {"green", "yellow", "red"}


def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/alerts")
    @login_required
    def api_alerts():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        conn=get_conn(); cur=conn.cursor()
        station_id = request.args.get("station_id")
        if me["role"] in ("admin","auditor","contador"):
            if station_id:
                cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id WHERE a.station_id=? ORDER BY a.id DESC LIMIT 500", (station_id,))
            else:
                cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id ORDER BY a.id DESC LIMIT 500")
            rows=[dict(r) for r in cur.fetchall()]
        elif me["role"]=="jefe_estacion":
            sid_me=ctx.require_station(me)
            cur.execute("SELECT group_name FROM stations WHERE id=?", (sid_me,))
            r=cur.fetchone(); g=(r["group_name"] if r else None)
            if station_id:
                if g:
                    cur.execute("SELECT 1 FROM stations WHERE id=? AND group_name=?", (station_id,g))
                    ok=cur.fetchone() is not None
                else:
                    ok=(int(station_id)==int(sid_me))
                if not ok:
                    conn.close(); return jsonify({"error":"forbidden_station"}),403
                cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id WHERE a.station_id=? ORDER BY a.id DESC LIMIT 500",(station_id,))
            else:
                if g:
                    cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id WHERE st.group_name=? ORDER BY a.id DESC LIMIT 500",(g,))
                else:
                    cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id WHERE a.station_id=? ORDER BY a.id DESC LIMIT 500",(sid_me,))
            rows=[dict(r) for r in cur.fetchall()]
        else:
            try:
                sid=ctx.require_station(me)
            except Exception:
                conn.close();
                return jsonify({"error":"station_required"}),400
            cur.execute("SELECT a.*, st.name as station_name FROM alerts a LEFT JOIN stations st ON st.id=a.station_id WHERE a.station_id=? ORDER BY a.id DESC LIMIT 500",(sid,))
            rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"alerts": rows})

    @app.post("/api/alerts")
    @login_required
    def api_alert_create():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        data=request.get_json(silent=True) or {}
        sid=None
        if me["role"]=="admin":
            try:
                sid=int(data.get("station_id") or 0)
            except Exception:
                sid=0
            if sid<=0:
                return jsonify({"error":"station_id_required"}),400
        elif me["role"]=="jefe_estacion":
            try:
                sid_me=ctx.require_station(me)
            except Exception:
                return jsonify({"error":"station_required"}),400
            try:
                sid=int(data.get("station_id") or sid_me)
            except Exception:
                sid=sid_me
            conn=get_conn(); cur=conn.cursor()
            cur.execute("SELECT group_name FROM stations WHERE id=?", (sid_me,))
            r=cur.fetchone(); g=(r["group_name"] if r else None)
            if g:
                cur.execute("SELECT 1 FROM stations WHERE id=? AND group_name=?", (sid,g))
                ok=cur.fetchone() is not None
            else:
                ok=(sid==sid_me)
            cur.execute("SELECT monthly_status FROM stations WHERE id=?", (sid,))
            st=cur.fetchone(); conn.close()
            if not ok:
                return jsonify({"error":"forbidden_station"}),403
            if (st and st["monthly_status"] in ("view_only","expired")):
                return jsonify({"error":"station_blocked"}),403
        else:
            if ctx.station_blocked(me):
                return jsonify({"error":"station_blocked"}),403
            try:
                sid=ctx.require_station(me)
            except Exception:
                return jsonify({"error":"station_required"}),400
        sev=data.get("severity")
        title=(data.get("title") or "").strip()
        if sev not in ALLOWED_ALERT_SEV or not title:
            return jsonify({"error":"invalid"}),400
        conn=get_conn(); cur=conn.cursor()
        cur.execute("INSERT INTO alerts (station_id,severity,title,description,created_by) VALUES (?,?,?,?,?)",
                    (sid, sev, title, data.get("description"), me["id"]))
        aid=cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me,"create_alert","alerts",str(aid),{"severity":sev})
        # Station-level alerts: notify ONLY admin(s) + chief(s) of the station.
        ctx.notify_admins_and_station_chiefs(
            sid,
            "Nueva alerta",
            title,
            "/mod/alerts",
            exclude_user_id=me.get("id"),
        )
        return jsonify({"ok":True,"id":aid})

    @app.post("/api/alerts/<int:alert_id>/close")
    @login_required
    @role_required("admin","jefe_estacion")
    def api_alert_close(alert_id):
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT station_id FROM alerts WHERE id=?", (alert_id,))
        row=cur.fetchone()
        if not row:
            conn.close(); return jsonify({"error":"not_found"}),404
        sid=row["station_id"]
        if me["role"]!="admin":
            if me["role"]=="jefe_estacion":
                sid_me=ctx.require_station(me)
                cur.execute("SELECT group_name FROM stations WHERE id=?", (sid_me,))
                r=cur.fetchone(); g=(r["group_name"] if r else None)
                if g:
                    cur.execute("SELECT 1 FROM stations WHERE id=? AND group_name=?", (sid,g))
                    ok=cur.fetchone() is not None
                else:
                    ok=(int(sid)==int(sid_me))
                if not ok:
                    conn.close(); return jsonify({"error":"forbidden"}),403
            else:
                if int(me.get("station_id") or -1)!=int(sid):
                    conn.close(); return jsonify({"error":"forbidden"}),403
        cur.execute("UPDATE alerts SET status='closed', closed_by=?, closed_at=CURRENT_TIMESTAMP WHERE id=?", (me["id"], alert_id))
        conn.commit(); conn.close()
        ctx.log_action(me,"close_alert","alerts",str(alert_id))
        return jsonify({"ok":True})

    # ---------------- alert templates ----------------

    @app.get("/api/alert-templates")
    @login_required
    @role_required("admin","jefe_estacion")
    def api_alert_templates_list():
        if get_brand() == 'petroleum':
            abort(404)
        me = ctx.get_me()
        brand = get_brand()
        station_id = (request.args.get("station_id") or "").strip()
        conn = get_conn(); cur = conn.cursor()

        where = ["t.brand=?"]
        params = [brand]

        if me["role"] == "jefe_estacion":
            sid_me = ctx.require_station(me)
            where.append("(t.station_id IS NULL OR t.station_id=?)")
            params.append(int(sid_me))
        elif station_id:
            where.append("t.station_id=?")
            params.append(int(station_id))

        cur.execute(
            f"SELECT t.* FROM alert_templates t WHERE {' AND '.join(where)} ORDER BY t.id DESC LIMIT 500",
            tuple(params),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"templates": rows})

    @app.post("/api/alert-templates")
    @login_required
    @role_required("admin","jefe_estacion")
    def api_alert_template_create():
        if get_brand() == 'petroleum':
            abort(404)
        me = ctx.get_me()
        brand = get_brand()
        data = request.get_json(silent=True) or {}
        sev = (data.get("severity") or "").strip().lower()
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        station_id = data.get("station_id")

        if sev not in ALLOWED_ALERT_SEV or not title:
            return jsonify({"error":"invalid"}), 400

        if me["role"] == "jefe_estacion":
            sid_me = ctx.require_station(me)
            station_id = sid_me
        else:
            station_id = int(station_id or 0) or None

        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO alert_templates (brand, station_id, severity, title, description, created_by) VALUES (?,?,?,?,?,?)",
            (brand, station_id, sev, title, description or None, me["id"]),
        )
        tid = cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me, "create_alert_template", "alert_templates", str(tid), {"severity": sev})
        return jsonify({"ok": True, "id": tid})

    @app.post("/api/alert-templates/<int:template_id>/apply")
    @login_required
    @role_required("admin","jefe_estacion")
    def api_alert_template_apply(template_id: int):
        if get_brand() == 'petroleum':
            abort(404)
        """Create an alert from a template (notifies admins + station chief)."""
        me = ctx.get_me()
        brand = get_brand()
        data = request.get_json(silent=True) or {}
        station_id_override = int(data.get("station_id") or 0) or None

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM alert_templates WHERE id=? AND brand=?", (template_id, brand))
        t = cur.fetchone()
        if not t:
            conn.close();
            return jsonify({"error":"not_found"}), 404

        # Station resolution
        sid = station_id_override or t["station_id"]
        if me["role"] == "jefe_estacion":
            sid_me = ctx.require_station(me)
            sid = sid_me
        if not sid:
            conn.close();
            return jsonify({"error":"station_id_required"}), 400

        cur.execute(
            "INSERT INTO alerts (brand, station_id, severity, title, description, created_by) VALUES (?,?,?,?,?,?)",
            (brand, int(sid), t["severity"], t["title"], t["description"], me["id"]),
        )
        aid = cur.lastrowid
        conn.commit(); conn.close()

        ctx.log_action(me, "apply_alert_template", "alerts", str(aid), {"template_id": template_id})
        ctx.notify_admins_and_station_chiefs(int(sid), "Nueva alerta", t["title"], "/mod/alerts", exclude_user_id=me.get("id"), ntype="alert", brand=brand)
        return jsonify({"ok": True, "id": aid})

    # ---------------- pipas ----------------

from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand

# Allowed kinds from UI (templates/mod/maintenance.html)
ALLOWED_MAINT_KIND = {"preventivo", "correctivo", "calibracion"}



def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/pumps")
    @login_required
    def api_pumps():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        brand=get_brand()
        conn=get_conn(); cur=conn.cursor()
        # Optional filter by station_id for admin/jefe
        station_id = request.args.get("station_id")
        if me["role"]=="admin":
            if station_id:
                cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id WHERE p.station_id=? ORDER BY p.id DESC", (station_id,))
            else:
                cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id ORDER BY p.id DESC")
        elif me["role"]=="jefe_estacion":
            sid_me=ctx.require_station(me)
            cur.execute("SELECT group_name FROM stations WHERE id=?", (sid_me,))
            r=cur.fetchone(); g=(r["group_name"] if r else None)
            if station_id:
                # validate station_id belongs to group
                if g:
                    cur.execute("SELECT 1 FROM stations WHERE id=? AND group_name=?", (station_id, g))
                    ok = cur.fetchone() is not None
                else:
                    ok = (int(station_id)==int(sid_me))
                if not ok:
                    conn.close(); return jsonify({"error":"forbidden_station"}),403
                cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id WHERE p.station_id=? ORDER BY p.id DESC",(station_id,))
            else:
                if g:
                    cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id WHERE st.group_name=? ORDER BY p.id DESC", (g,))
                else:
                    cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id WHERE p.station_id=? ORDER BY p.id DESC", (sid_me,))
        else:
            sid=ctx.require_station(me)
            cur.execute("SELECT p.*, st.name as station_name FROM pumps p LEFT JOIN stations st ON st.id=p.station_id WHERE p.station_id=? ORDER BY p.id DESC", (sid,))
        rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"pumps": rows})

    @app.post("/api/pumps")
    @login_required
    def api_pump_create():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        data=request.get_json(silent=True) or {}
        # station selection for admin/jefe
        sid=None
        if me["role"]=="admin":
            try:
                sid=int(data.get("station_id") or 0)
            except Exception:
                sid=0
            if sid<=0:
                return jsonify({"error":"station_id_required"}),400
        elif me["role"]=="jefe_estacion":
            sid_me=ctx.require_station(me)
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
            sid=ctx.require_station(me)
        code=(data.get("pump_code") or "").strip()
        if not code:
            return jsonify({"error":"pump_code_required"}),400
        conn=get_conn(); cur=conn.cursor()
        cur.execute("INSERT INTO pumps (station_id,pump_code,location,status) VALUES (?,?,?,?)",
                    (sid, code, data.get("location"), data.get("status","green")))
        pid=cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me,"create_pump","pumps",str(pid))
        return jsonify({"ok":True,"id":pid})

    @app.get("/api/maintenance")
    @login_required
    def api_maintenance():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        conn=get_conn(); cur=conn.cursor()
        station_id = request.args.get("station_id")
        if me["role"] in ("admin","auditor"):
            cur.execute(
                "SELECT m.*, st.name as station_name, p.pump_code FROM maintenance m "
                "LEFT JOIN stations st ON st.id=m.station_id "
                "LEFT JOIN pumps p ON p.id=m.pump_id "
                + ("WHERE m.station_id=? " if station_id else "") +
                "ORDER BY m.id DESC LIMIT 500",
                ((station_id,) if station_id else tuple()),
            )
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
                cur.execute(
                    "SELECT m.*, st.name as station_name, p.pump_code FROM maintenance m "
                    "LEFT JOIN stations st ON st.id=m.station_id "
                    "LEFT JOIN pumps p ON p.id=m.pump_id "
                    "WHERE m.station_id=? ORDER BY m.id DESC LIMIT 500",
                    (station_id,),
                )
            else:
                if g:
                    cur.execute(
                        "SELECT m.*, st.name as station_name, p.pump_code FROM maintenance m "
                        "LEFT JOIN stations st ON st.id=m.station_id "
                        "LEFT JOIN pumps p ON p.id=m.pump_id "
                        "WHERE st.group_name=? ORDER BY m.id DESC LIMIT 500",
                        (g,),
                    )
                else:
                    cur.execute(
                        "SELECT m.*, st.name as station_name, p.pump_code FROM maintenance m "
                        "LEFT JOIN stations st ON st.id=m.station_id "
                        "LEFT JOIN pumps p ON p.id=m.pump_id "
                        "WHERE m.station_id=? ORDER BY m.id DESC LIMIT 500",
                        (sid_me,),
                    )
            rows=[dict(r) for r in cur.fetchall()]
        else:
            sid=ctx.require_station(me)
            cur.execute(
                "SELECT m.*, st.name as station_name, p.pump_code FROM maintenance m "
                "LEFT JOIN stations st ON st.id=m.station_id "
                "LEFT JOIN pumps p ON p.id=m.pump_id "
                "WHERE m.station_id=? ORDER BY m.id DESC LIMIT 500",
                (sid,),
            )
            rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"maintenance": rows})

    @app.post("/api/maintenance")
    @login_required
    def api_maintenance_create():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        form=request.form
        sid=None
        if me["role"]=="admin":
            try:
                sid=int(form.get("station_id") or 0)
            except Exception:
                sid=0
            if sid<=0:
                return jsonify({"error":"station_id_required"}),400
        elif me["role"]=="jefe_estacion":
            sid_me=ctx.require_station(me)
            try:
                sid=int(form.get("station_id") or sid_me)
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
            sid=ctx.require_station(me)
        kind=form.get("kind")
        if kind not in ALLOWED_MAINT_KIND:
            return jsonify({"error":"invalid_kind"}),400
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
        allowed_ext = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_magic = {"pdf", "png", "jpg"}
        before = ctx.save_upload_checked(request.files.get("before"), f"stations/{sid}/maintenance", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        after = ctx.save_upload_checked(request.files.get("after"), f"stations/{sid}/maintenance", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        pump_id=form.get("pump_id")
        pump_id=int(pump_id) if pump_id else None
        brand = get_brand()
        conn=get_conn(); cur=conn.cursor()
        cur.execute(
            "INSERT INTO maintenance (brand, station_id,pump_id,kind,technician,notes,evidence_before,evidence_after,created_by) VALUES (?, ?,?,?,?,?,?,?,?)",
            (brand, sid, pump_id, kind, form.get("technician"), form.get("notes"), before, after, me["id"]),
        )
        mid=cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me,"create_maintenance","maintenance",str(mid))

        # Station-level maintenance: notify ONLY admin(s) + chief(s) of the station.
        ctx.notify_admins_and_station_chiefs(
            sid,
            "Nuevo mantenimiento",
            kind,
            "/mod/maintenance",
            exclude_user_id=me.get("id"),
        )
        return jsonify({"ok":True,"id":mid})

    # ---------------- bitacoras ----------------

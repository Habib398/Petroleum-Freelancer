from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand

# Allowed fuel types from UI (templates/mod/pipas.html)
ALLOWED_FUEL = {"magna", "premium", "diesel"}



def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/pipas")
    @login_required
    def api_pipas():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        brand=get_brand()
        conn=get_conn(); cur=conn.cursor()
        if me["role"] in ("admin","auditor"):
            cur.execute("SELECT p.*, st.name as station_name FROM pipas p LEFT JOIN stations st ON st.id=p.station_id WHERE p.brand=? ORDER BY p.id DESC LIMIT 500",(brand,))
            rows=[dict(r) for r in cur.fetchall()]
        elif me["role"]=="jefe_estacion":
            # Jefe: ver todas las estaciones del mismo grupo
            sid=ctx.require_station(me)
            cur.execute("SELECT group_name FROM stations WHERE id=?", (sid,))
            r=cur.fetchone()
            g=(r["group_name"] if r else None)
            if g:
                cur.execute(
                    "SELECT p.*, st.name as station_name FROM pipas p "
                    "LEFT JOIN stations st ON st.id=p.station_id "
                    "WHERE p.brand=? AND st.group_name=? ORDER BY p.id DESC LIMIT 500",
                    (brand, g),
                )
            else:
                cur.execute("SELECT p.*, st.name as station_name FROM pipas p LEFT JOIN stations st ON st.id=p.station_id WHERE p.brand=? AND p.station_id=? ORDER BY p.id DESC LIMIT 500",(brand,sid,))
            rows=[dict(r) for r in cur.fetchall()]
        else:
            sid=ctx.require_station(me)
            cur.execute("SELECT p.*, st.name as station_name FROM pipas p LEFT JOIN stations st ON st.id=p.station_id WHERE p.brand=? AND p.station_id=? ORDER BY p.id DESC LIMIT 500",(brand,sid,))
            rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"pipas": rows})

    @app.post("/api/pipas")
    @login_required
    def api_pipa_create():
        if get_brand() == 'petroleum':
            abort(404)
        me=ctx.get_me()
        # Station selection:
        # - Operador: fixed station
        # - Jefe: any station in their group
        # - Admin: may choose station_id explicitly
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
        fuel=form.get("fuel_type")
        liters=float(form.get("liters") or 0)
        if fuel not in ALLOWED_FUEL or liters<=0:
            return jsonify({"error":"invalid_fuel_or_liters"}),400
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
        allowed_ext = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_magic = {"pdf", "png", "jpg"}
        rel_ticket = ctx.save_upload_checked(request.files.get("ticket"), f"stations/{sid}/pipas", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        rel_factura = ctx.save_upload_checked(request.files.get("factura"), f"stations/{sid}/pipas", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        rel_before = ctx.save_upload_checked(request.files.get("before"), f"stations/{sid}/pipas", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        rel_after = ctx.save_upload_checked(request.files.get("after"), f"stations/{sid}/pipas", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        conn=get_conn(); cur=conn.cursor()
        cur.execute(
            "INSERT INTO pipas (brand, station_id, plates, operator_name, arrival_time, departure_time, fuel_type, liters, ticket_path, factura_path, before_path, after_path, signature_name, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (get_brand(), sid, form.get("plates"), form.get("operator_name"), form.get("arrival_time"), form.get("departure_time"), fuel, liters, rel_ticket, rel_factura, rel_before, rel_after, form.get("signature_name"), me["id"]),
        )
        pid=cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me,"create_pipa","pipas",str(pid),{"fuel":fuel,"liters":liters})
        # Station-level records: notify ONLY admin(s) + chief(s) of the station.
        ctx.notify_admins_and_station_chiefs(
            sid,
            "Nueva pipa registrada",
            f"{fuel} {liters} L",
            "/mod/pipas",
            exclude_user_id=me.get("id"),
        )
        return jsonify({"ok":True,"id":pid})

    # ---------------- pumps & maintenance ----------------

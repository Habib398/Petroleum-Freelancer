from __future__ import annotations
import json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user


def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/bitacoras")
    @login_required
    def api_bitacoras():
        me=ctx.get_me()
        conn=get_conn(); cur=conn.cursor()
        if me["role"] in ("admin","auditor"):
            cur.execute("SELECT b.*, st.name as station_name, u.username as user_name FROM bitacoras b LEFT JOIN stations st ON st.id=b.station_id LEFT JOIN users u ON u.id=b.created_by ORDER BY b.id DESC LIMIT 500")
            rows=[dict(r) for r in cur.fetchall()]
        else:
            sid=ctx.require_station(me)
            cur.execute("SELECT b.*, st.name as station_name, u.username as user_name FROM bitacoras b LEFT JOIN stations st ON st.id=b.station_id LEFT JOIN users u ON u.id=b.created_by WHERE b.station_id=? ORDER BY b.id DESC LIMIT 500",(sid,))
            rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"bitacoras": rows})

    @app.post("/api/bitacoras")
    @login_required
    def api_bitacora_create():
        me=ctx.get_me()
        if ctx.station_blocked(me):
            return jsonify({"error":"station_blocked"}),403
        sid=ctx.require_station(me)
        kind=request.form.get("kind")
        ref_date=request.form.get("ref_date")
        notes=request.form.get("notes","")
        if kind not in ALLOWED_BITACORA_KIND or not ref_date:
            return jsonify({"error":"invalid"}),400
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
        allowed_ext = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_magic = {"pdf", "png", "jpg"}
        ev = ctx.save_upload_checked(request.files.get("evidence"), f"stations/{sid}/bitacoras", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        conn=get_conn(); cur=conn.cursor()
        cur.execute(
            "INSERT INTO bitacoras (station_id,kind,ref_date,notes,evidence_path,created_by) VALUES (?,?,?,?,?,?)",
            (sid,kind,ref_date,notes,ev,me["id"]),
        )
        bid=cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me,"create_bitacora","bitacoras",str(bid))
        return jsonify({"ok":True,"id":bid})

    # ---------------- profile / FIEL ----------------


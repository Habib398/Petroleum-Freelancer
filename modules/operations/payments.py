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

    @app.get("/api/payments")
    @login_required
    def api_payments():
        me=ctx.get_me()
        if me and me.get("role")=="operador":
            return jsonify({"error":"forbidden"}),403
        brand = get_brand()
        conn=get_conn(); cur=conn.cursor()
        if me["role"] in ("admin","contador","auditor"):
            cur.execute(
                "SELECT p.*, st.name as station_name FROM payments p LEFT JOIN stations st ON st.id=p.station_id WHERE p.brand=? ORDER BY p.id DESC LIMIT 500",
                (brand,),
            )
            rows=[dict(r) for r in cur.fetchall()]
        else:
            sid=ctx.require_station(me)
            cur.execute(
                "SELECT p.*, st.name as station_name FROM payments p LEFT JOIN stations st ON st.id=p.station_id WHERE p.brand=? AND p.station_id=? ORDER BY p.id DESC LIMIT 500",
                (brand, sid),
            )
            rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"payments": rows})

    @app.post("/api/payments/proof")
    @login_required
    def api_payment_proof():
        me=ctx.get_me()
        if me and me.get("role")=="operador":
            return jsonify({"error":"forbidden"}),403
        brand = get_brand()

        sid = request.form.get("station_id")
        if sid in (None, "", "null", "None"):
            sid = me.get("station_id") if me else None
        if sid in (None, "", "null", "None"):
            return jsonify({"error":"station_required"}),400
        try:
            sid = int(sid)
        except Exception:
            return jsonify({"error":"invalid_station_id"}),400

        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT id FROM stations WHERE id=? AND brand=?", (sid, brand))
        st = cur.fetchone()
        conn.close()
        if not st:
            return jsonify({"error":"station_not_found"}),404
        if me.get("role") != "admin" and not ctx.can_access_station(me, sid):
            return jsonify({"error":"forbidden_station"}),403

        # allow even if blocked
        proof=request.files.get("proof")
        if not proof:
            return jsonify({"error":"proof_required"}),400
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
        allowed_ext = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_magic = {"pdf", "png", "jpg"}
        rel = ctx.save_upload_checked(proof, f"stations/{sid}/payments", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        period_start=request.form.get("period_start")
        period_end=request.form.get("period_end")
        conn=get_conn(); cur=conn.cursor()
        cur.execute(
            "INSERT INTO payments (brand, station_id, period_start, period_end, proof_path, status) VALUES (?,?,?,?,?, 'pending')",
            (brand, sid, period_start, period_end, rel),
        )
        pid=cur.lastrowid
        conn.commit()
        # set station to view_only automatically
        cur.execute("UPDATE stations SET monthly_status='view_only' WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        ctx.log_action(me,"upload_payment_proof","payments",str(pid))
        # Admins must be notified when a station uploads payment proof.
        ctx.notify_admins("Pago por revisar", f"Estación {sid} subió comprobante", "/admin/inbox", station_id=sid, ntype="payment")
        # Extra: contador users (if you use that role)
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT id FROM users WHERE role='contador' AND is_active=1 AND (allowed_brands LIKE ? OR primary_brand=? OR brand=?)", (f"%{brand}%", brand, brand))
        ids=[r["id"] for r in cur.fetchall()]
        conn.close()
        for uid in ids:
            ctx.notify(uid, sid, "Pago por revisar", f"Estación {sid} subió comprobante", "/admin/inbox", ntype="payment")
        return jsonify({"ok":True,"id":pid,"path":rel})

    @app.post("/api/payments/<int:payment_id>/review")
    @login_required
    @role_required("admin","contador")
    def api_payment_review(payment_id):
        me=ctx.get_me()
        if me and me.get("role")=="operador":
            return jsonify({"error":"forbidden"}),403
        brand = get_brand()
        status=request.form.get("status")  # validated/rejected
        if status not in ("validated","rejected"):
            return jsonify({"error":"invalid_status"}),400
        invoice=request.files.get("invoice")
        invoice_rel=""
        if status=="validated":
            if not invoice:
                return jsonify({"error":"invoice_required"}),400
            limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))
            allowed_ext = {".pdf"}
            allowed_magic = {"pdf"}
            invoice_rel = ctx.save_upload_checked(invoice, "invoices", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT station_id FROM payments WHERE id=? AND brand=?", (payment_id, brand))
        row=cur.fetchone()
        if not row:
            conn.close(); return jsonify({"error":"not_found"}),404
        sid=row["station_id"]
        cur.execute(
            "UPDATE payments SET status=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP, invoice_path=? WHERE id=? AND brand=?",
            (status, me["id"], invoice_rel, payment_id, brand),
        )
        if status == "validated":
            cur.execute("UPDATE stations SET monthly_status='active' WHERE id=?", (sid,))
        elif status == "rejected":
            cur.execute("UPDATE stations SET monthly_status='expired' WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        ctx.log_action(me,"review_payment","payments",str(payment_id),{"status":status})
        # Notify only accounting/admin roles about the payment outcome.
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT id FROM users WHERE role='contador' AND is_active=1 AND (allowed_brands LIKE ? OR primary_brand=? OR brand=?)", (f"%{brand}%", brand, brand))
        contador_ids=[r["id"] for r in cur.fetchall()]
        conn.close()
        for uid in contador_ids:
            ctx.notify(uid, sid, f"Pago {status}", "Revisa la mensualidad de la estación.", "/admin/inbox", ntype="payment")
        # Notify admins of payment outcome too.
        ctx.notify_admins(f"Pago {status}", f"Estación {sid} · Revisión de mensualidad", "/admin/inbox", station_id=sid, exclude_user_id=me.get("id"), ntype="payment")
        return jsonify({"ok":True})

    # ---------------- alerts ----------------
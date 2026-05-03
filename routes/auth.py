from __future__ import annotations
import os, json, datetime
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services import reminders




# --------- shared decorators (for modules importing from routes.auth) ---------
from functools import wraps

def login_required(fn):
    """Require an authenticated session for the current request."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            # API -> JSON 401, Pages -> redirect
            try:
                if request.path.startswith('/api/') or request.is_json or 'application/json' in (request.headers.get('Accept') or ''):
                    return jsonify({'error': 'auth_required'}), 401
            except Exception:
                pass
            return redirect('/login')
        return fn(*args, **kwargs)
    return wrapper

def role_required(*roles):
    """Require the logged-in user to have one of the provided roles."""
    roles_set = set([r for r in roles if r])
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                return login_required(fn)(*args, **kwargs)
            # Prefer cached role in session; fallback to DB lookup
            user_role = session.get('role')
            if not user_role:
                try:
                    me = get_user(session.get('user_id'))
                    user_role = (me or {}).get('role')
                    if user_role:
                        session['role'] = user_role
                except Exception:
                    user_role = None
            if roles_set and user_role not in roles_set:
                try:
                    if request.path.startswith('/api/') or request.is_json or 'application/json' in (request.headers.get('Accept') or ''):
                        return jsonify({'error': 'forbidden'}), 403
                except Exception:
                    pass
                return abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco

def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.post("/api/auth/login")
    def api_login():
        # Basic rate limit: 8 attempts / 10 minutes per IP
        import time
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or "unknown"
        bucket = app.extensions.get("rate_login")
        now = int(time.time())
        window = 600
        limit = 8
        rec = bucket.get(ip) if isinstance(bucket, dict) else None
        if rec and now - rec.get("ts", 0) <= window and rec.get("fails", 0) >= limit:
            return jsonify({"error": "rate_limited", "message": "Demasiados intentos. Intenta más tarde."}), 429

        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        user, verr = verify_user(username, password, ip=ip)
        if not user:
            # track failed attempts per IP (anti-bruteforce)
            if isinstance(bucket, dict):
                if not rec or now - rec.get("ts", 0) > window:
                    rec = {"ts": now, "fails": 0}
                rec["fails"] = int(rec.get("fails", 0)) + 1
                rec["ts"] = now
                bucket[ip] = rec

            if verr == "user_locked":
                return jsonify({"error": "user_locked", "message": "Usuario bloqueado temporalmente. Intenta más tarde."}), 423
            if verr == "user_inactive":
                return jsonify({"error": "user_inactive", "message": "Usuario inactivo"}), 403
            return jsonify({"error": "invalid_credentials"}), 401

        # reset failures on success
        if isinstance(bucket, dict) and ip in bucket:
            bucket.pop(ip, None)
        session["user_id"] = user["id"]
        session["role"] = user.get("role")
        me = ctx.get_me()
        ctx.log_action(me, "login", "auth", str(user["id"]))
        try:
            reminders.run_for_user(me)
        except Exception:
            pass
        return jsonify({"ok": True})

    # --- Password reset (admin-assisted, ISO-friendly) ---
    @app.post("/api/auth/request-reset")
    @login_required
    @role_required("admin")
    def api_request_reset():
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        if not username:
            return jsonify({"ok": False, "error": "missing_username"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, is_active FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row or int(row["is_active"] or 0) != 1:
            conn.close()
            return jsonify({"ok": False, "error": "user_not_found"}), 404

        import time, hashlib, secrets
        token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = int(time.time()) + int(os.environ.get("COG_RESET_TTL_MIN", "30")) * 60
        ip_req = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or "unknown"

        cur.execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at, request_ip) VALUES (?,?,?,?)",
            (row["id"], token_hash, expires_at, ip_req),
        )
        conn.commit(); conn.close()

        me = ctx.get_me()
        ctx.log_action(me, "request_password_reset", "users", str(row["id"]), {"username": username, "expires_at": expires_at, "ip": ip_req})

        # Return token (admin will share it securely with the user)
        return jsonify({"ok": True, "token": token, "expires_at": expires_at})

    @app.post("/api/auth/reset-password")
    def api_reset_password():
        """Reset password using a token (user flow).

        This endpoint is allowed without login. It is safe because the token is random and short-lived.
        """
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        new_password = (data.get("new_password") or "").strip()
        if not token or not new_password:
            return jsonify({"ok": False, "error": "missing_fields"}), 400

        min_len = int(os.environ.get("COG_PASSWORD_MIN_LEN", "8") or 8)
        if len(new_password) < min_len:
            return jsonify({"ok": False, "error": "weak_password", "message": f"La contraseña debe tener al menos {min_len} caracteres"}), 400

        import time, hashlib
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())

        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT id, user_id, expires_at, used_at FROM password_resets WHERE token_hash=? ORDER BY id DESC LIMIT 1",
            (token_hash,),
        )
        r = cur.fetchone()
        if not r or r["used_at"] or int(r["expires_at"] or 0) < now:
            conn.close()
            return jsonify({"ok": False, "error": "invalid_or_expired_token"}), 400

        cur.execute(
            "UPDATE users SET password_hash=?, password_updated_at=CURRENT_TIMESTAMP, failed_attempts=0, locked_until=NULL WHERE id=?",
            (generate_password_hash(new_password), r["user_id"]),
        )
        cur.execute("UPDATE password_resets SET used_at=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))
        conn.commit(); conn.close()

        return jsonify({"ok": True})

    @app.post("/api/auth/force-reset")
    @login_required
    @role_required("admin")
    def api_force_reset():
        """Admin-only immediate password reset (no token)."""
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        new_password = (data.get("new_password") or "").strip()
        if not user_id or not new_password:
            return jsonify({"ok": False, "error": "missing_fields"}), 400

        min_len = int(os.environ.get("COG_PASSWORD_MIN_LEN", "8") or 8)
        if len(new_password) < min_len:
            return jsonify({"ok": False, "error": "weak_password"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id=?", (int(user_id),))
        u = cur.fetchone()
        if not u:
            conn.close()
            return jsonify({"ok": False, "error": "user_not_found"}), 404

        cur.execute(
            "UPDATE users SET password_hash=?, password_updated_at=CURRENT_TIMESTAMP, failed_attempts=0, locked_until=NULL WHERE id=?",
            (generate_password_hash(new_password), int(user_id)),
        )
        conn.commit(); conn.close()

        me = ctx.get_me()
        ctx.log_action(me, "force_password_reset", "users", str(user_id))
        return jsonify({"ok": True})


    @app.get("/api/me")
    @login_required
    def api_me():
        me = ctx.get_me()
        return jsonify({"me": me})

    # ---------------- downloads ----------------
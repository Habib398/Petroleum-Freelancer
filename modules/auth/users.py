from __future__ import annotations
import json, datetime, re, sqlite3
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from services.brand import get_brand

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_station_id(raw):
    if raw in (None, "", "null", "None"):
        return None
    try:
        sid = int(raw)
    except Exception:
        return "invalid"
    return sid if sid > 0 else "invalid"


def _station_exists(conn, station_id: int, brand: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM stations WHERE id=? AND brand=?", (station_id, brand))
    return cur.fetchone() is not None


def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/users")
    @login_required
    @role_required("admin")
    def api_users():
        conn = get_conn(); cur = conn.cursor()
        brand = get_brand()
        cur.execute("SELECT u.*, s.name as station_name FROM users u LEFT JOIN stations s ON s.id=u.station_id WHERE u.allowed_brands LIKE ? ORDER BY u.id DESC", (f"%{brand}%",))
        rows=[dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"users": rows})

    @app.post("/api/users")
    @login_required
    @role_required("admin")
    def api_user_create():
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        role = (data.get("role") or "").strip()
        station_id = _normalize_station_id(data.get("station_id"))
        email = (data.get("email") or "").strip().lower()
        raw_allowed_brands = data.get("allowed_brands")
        if isinstance(raw_allowed_brands, (list, tuple, set)):
            allowed_brands = ",".join(str(x).strip().lower() for x in raw_allowed_brands if str(x).strip())
        else:
            allowed_brands = (raw_allowed_brands or "").strip().lower()
        if role not in ("admin","operador","jefe_estacion","contador","auditor"):
            return jsonify({"error":"invalid_role"}), 400
        if not username or not password:
            return jsonify({"error":"missing_username_or_password"}), 400
        if station_id == "invalid":
            return jsonify({"error":"invalid_station_id"}), 400
        if email and not EMAIL_RX.match(email):
            return jsonify({"error":"invalid_email"}), 400
        brand = get_brand()
        if not allowed_brands:
            allowed_brands = brand
        # normalize allowed_brands
        allowed = [p.strip() for p in allowed_brands.split(",") if p.strip()]
        allowed = [p for p in allowed if p in ("consulting","petroleum")]
        if not allowed:
            allowed = [brand]
        allowed_brands = ",".join(sorted(set(allowed)))

        if role in {"operador","jefe_estacion"} and not station_id:
            return jsonify({"error":"station_required"}), 400
        conn = get_conn(); cur = conn.cursor()
        if station_id is not None and not _station_exists(conn, int(station_id), brand):
            conn.close()
            return jsonify({"error":"station_not_found"}), 404
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, station_id, email, allowed_brands, primary_brand) VALUES (?,?,?,?,?,?,?)",
                (username, generate_password_hash(password), role, station_id if role in {"operador","jefe_estacion"} else station_id, email or None, allowed_brands, brand),
            )
            uid = cur.lastrowid
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            conn.close()
            msg = str(e).lower()
            if "users.username" in msg or "unique" in msg:
                return jsonify({"error":"username_exists"}), 409
            if "foreign key" in msg:
                return jsonify({"error":"station_not_found"}), 404
            return jsonify({"error":"integrity_error"}), 400
        conn.close()
        me = ctx.get_me()
        ctx.log_action(me, "create_user", "users", str(uid), {"role": role, "station_id": station_id})
        return jsonify({"ok": True, "id": uid})

    @app.put("/api/users/<int:user_id>")
    @login_required
    @role_required("admin")
    def api_user_update(user_id):
        data = request.get_json(silent=True) or {}
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT id, role, station_id FROM users WHERE id=?", (user_id,))
        current = cur.fetchone()
        if not current:
            conn.close()
            return jsonify({"error":"not_found"}), 404
        brand = get_brand()
        new_role = (data.get("role") if "role" in data else current.get("role"))
        station_id = _normalize_station_id(data.get("station_id")) if "station_id" in data else current.get("station_id")
        if station_id == "invalid":
            conn.close()
            return jsonify({"error":"invalid_station_id"}), 400
        if new_role not in ("admin","operador","jefe_estacion","contador","auditor"):
            conn.close()
            return jsonify({"error":"invalid_role"}), 400
        if new_role in {"operador","jefe_estacion"} and not station_id:
            conn.close()
            return jsonify({"error":"station_required"}), 400
        if station_id is not None and not _station_exists(conn, int(station_id), brand):
            conn.close()
            return jsonify({"error":"station_not_found"}), 404

        sets=[]; vals=[]
        if "password" in data and data["password"]:
            sets.append("password_hash=?"); vals.append(generate_password_hash(data["password"]))
        if "email" in data:
            email = (data.get("email") or "").strip().lower()
            if email and not EMAIL_RX.match(email):
                conn.close()
                return jsonify({"error":"invalid_email"}), 400
            sets.append("email=?"); vals.append(email or None)
        for f in ["role","is_active","username"]:
            if f in data:
                sets.append(f"{f}=?"); vals.append(data[f])
        if "station_id" in data or "role" in data:
            sets.append("station_id=?"); vals.append(station_id if new_role in {"operador","jefe_estacion","contador","auditor"} else None)
        if not sets:
            conn.close()
            return jsonify({"error":"no_changes"}), 400
        vals.append(user_id)
        try:
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(vals))
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            conn.close()
            msg = str(e).lower()
            if "users.username" in msg or "unique" in msg:
                return jsonify({"error":"username_exists"}), 409
            if "foreign key" in msg:
                return jsonify({"error":"station_not_found"}), 404
            return jsonify({"error":"integrity_error"}), 400
        conn.close()
        me=ctx.get_me()
        ctx.log_action(me,"update_user","users",str(user_id),{"fields":list(data.keys())})
        return jsonify({"ok":True})

    
    @app.delete("/api/users/<int:user_id>")
    @login_required
    @role_required("admin")
    def api_user_delete(user_id):
        me = ctx.get_me()
        # Prevent self-deletion
        if me and int(me.get("id", -1)) == int(user_id):
            return jsonify({"error":"cannot_delete_self"}), 400

        conn = get_conn(); cur = conn.cursor()
        # Ensure user exists
        cur.execute("SELECT id, role FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"error":"not_found"}), 404

        # Prevent deleting last admin
        if row["role"] == "admin":
            cur.execute("SELECT COUNT(*) as c FROM users WHERE role='admin' AND is_active=1")
            c = int(cur.fetchone()["c"])
            if c <= 1:
                conn.close()
                return jsonify({"error":"cannot_delete_last_admin"}), 400

        cur.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit(); conn.close()
        ctx.log_action(me, "delete_user", "users", str(user_id), {})
        return jsonify({"ok": True})

    # ---------------- station access delegation ----------------
    @app.get("/api/users/<int:user_id>/station-access")
    @login_required
    @role_required("admin")
    def api_user_station_access_get(user_id: int):
        """Return delegated station access for a user (current brand)."""
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT station_id FROM user_station_access WHERE brand=? AND user_id=? ORDER BY station_id ASC",
            (brand, user_id),
        )
        ids = [int(r["station_id"]) for r in cur.fetchall()]
        conn.close()
        return jsonify({"brand": brand, "user_id": user_id, "stations": ids})

    @app.put("/api/users/<int:user_id>/station-access")
    @login_required
    @role_required("admin")
    def api_user_station_access_set(user_id: int):
        """Set delegated station access for a user (current brand).

        Body: {stations:[1,2,3]}
        """
        me = ctx.get_me()
        brand = get_brand()
        data = request.get_json(silent=True) or {}
        stations = data.get("stations") or []
        if not isinstance(stations, list):
            return jsonify({"error": "bad_payload"}), 400
        # Normalize
        norm_ids = []
        for s in stations:
            try:
                sid = int(s)
                if sid > 0:
                    norm_ids.append(sid)
            except Exception:
                continue
        norm_ids = sorted(set(norm_ids))

        conn = get_conn(); cur = conn.cursor()
        # Ensure user exists
        cur.execute("SELECT id, role FROM users WHERE id=?", (user_id,))
        u = cur.fetchone()
        if not u:
            conn.close()
            return jsonify({"error": "not_found"}), 404

        # Validate stations before replacing rows
        if norm_ids:
            marks = ",".join(["?"] * len(norm_ids))
            cur.execute(
                f"SELECT id FROM stations WHERE brand=? AND id IN ({marks})",
                (brand, *norm_ids),
            )
            found = {int(r["id"]) for r in cur.fetchall()}
            missing = [sid for sid in norm_ids if sid not in found]
            if missing:
                conn.close()
                return jsonify({"error": "station_not_found", "missing": missing}), 404

        # Replace rows
        cur.execute("DELETE FROM user_station_access WHERE brand=? AND user_id=?", (brand, user_id))
        for sid in norm_ids:
            cur.execute(
                "INSERT OR IGNORE INTO user_station_access (user_id, station_id, brand) VALUES (?,?,?)",
                (user_id, sid, brand),
            )
        conn.commit(); conn.close()
        ctx.log_action(me, "set_user_station_access", "user_station_access", str(user_id), {"brand": brand, "stations": norm_ids})
        return jsonify({"ok": True, "stations": norm_ids})


# ---------------- activities catalog ----------------


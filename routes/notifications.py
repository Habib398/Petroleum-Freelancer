from __future__ import annotations

from flask import request, jsonify

from db import get_conn
from services.brand import get_brand


def _station_scope_for_user(conn, me: dict) -> dict:
    """Return station visibility scope.

    - admin: can see all stations
    - jefe_estacion: can see own station, and if station has group_name, all stations in that group
    - others: only own station
    """
    role = (me.get("role") or "").strip()
    if role == "admin":
        return {"mode": "all"}

    sid = me.get("station_id")
    if not sid:
        return {"mode": "none", "station_ids": []}

    if role == "jefe_estacion":
        cur = conn.cursor()
        cur.execute("SELECT group_name FROM stations WHERE id=?", (int(sid),))
        r = cur.fetchone()
        g = (r["group_name"] if r else None)
        if g:
            cur.execute("SELECT id FROM stations WHERE group_name=?", (g,))
            ids = [int(x["id"]) for x in cur.fetchall()]
            if int(sid) not in ids:
                ids.append(int(sid))
            return {"mode": "group", "station_ids": ids, "group_name": g}
        return {"mode": "single", "station_ids": [int(sid)]}

    return {"mode": "single", "station_ids": [int(sid)]}


def _visibility_clause(alias: str, scope: dict, me_id: int):
    if scope.get("mode") == "all":
        return f"({alias}.user_id=? OR {alias}.user_id IS NULL)", [int(me_id)]

    station_ids = [int(x) for x in (scope.get("station_ids") or []) if x is not None]
    if station_ids:
        in_clause = ",".join(["?"] * len(station_ids))
        sql = (
            f"({alias}.user_id=? OR ({alias}.user_id IS NULL AND "
            f"({alias}.station_id IS NULL OR {alias}.station_id IN ({in_clause}))))"
        )
        return sql, [int(me_id), *station_ids]

    return f"({alias}.user_id=? OR ({alias}.user_id IS NULL AND {alias}.station_id IS NULL))", [int(me_id)]


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/api/notifications")
    @login_required
    def api_notifications():
        """List notifications visible to the current user."""
        me = ctx.get_me()
        brand = get_brand()

        limit = min(max(int(request.args.get("limit") or 50), 1), 200)
        page = max(int(request.args.get("page") or 1), 1)
        offset = (page - 1) * limit

        only_unread = (request.args.get("unread") or "").strip() in ("1", "true", "yes")
        q = (request.args.get("q") or "").strip()
        ntype = (request.args.get("type") or "").strip()

        conn = None
        try:
            conn = get_conn()
            scope = _station_scope_for_user(conn, me)
            cur = conn.cursor()

            base = (
                "SELECT n.*, st.name AS station_name "
                "FROM notifications n "
                "LEFT JOIN stations st ON st.id=n.station_id "
            )

            vis_sql, vis_params = _visibility_clause("n", scope, int(me["id"]))
            where_parts = ["n.brand=?", vis_sql]
            params = [brand, *vis_params]

            if only_unread:
                where_parts.append("n.is_read=0")
            if ntype:
                where_parts.append("n.type=?")
                params.append(ntype)
            if q:
                where_parts.append("(n.title LIKE ? OR n.body LIKE ?)")
                like = f"%{q}%"
                params.extend([like, like])

            sql = base + "WHERE " + " AND ".join(where_parts) + " ORDER BY n.id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cur.execute(sql, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return jsonify({"notifications": rows, "page": page, "limit": limit, "has_more": len(rows) == limit})
        except Exception as e:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            return jsonify({"notifications": [], "page": page, "limit": limit, "has_more": False, "error": str(e)}), 500

    @app.get("/api/notifications/unread-count")
    @login_required
    def api_notifications_unread_count():
        me = ctx.get_me()
        conn = get_conn()
        scope = _station_scope_for_user(conn, me)
        cur = conn.cursor()
        brand = get_brand()

        vis_sql, vis_params = _visibility_clause("notifications", scope, int(me["id"]))
        cur.execute(
            "SELECT COUNT(1) AS c FROM notifications WHERE brand=? AND is_read=0 AND " + vis_sql,
            tuple([brand, *vis_params]),
        )

        c = int((cur.fetchone() or {"c": 0})["c"])
        conn.close()
        return jsonify({"unread": c})

    @app.post("/api/notifications/read-all")
    @login_required
    def api_notifications_read_all():
        me = ctx.get_me()
        brand = get_brand()
        conn = get_conn()
        scope = _station_scope_for_user(conn, me)
        cur = conn.cursor()

        vis_sql, vis_params = _visibility_clause("notifications", scope, int(me["id"]))
        cur.execute(
            "UPDATE notifications SET is_read=1 WHERE brand=? AND " + vis_sql,
            tuple([brand, *vis_params]),
        )

        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.post("/api/notifications/<int:nid>/read")
    @login_required
    def api_notifications_read(nid: int):
        me = ctx.get_me()
        brand = get_brand()
        conn = get_conn()
        scope = _station_scope_for_user(conn, me)
        cur = conn.cursor()

        vis_sql, vis_params = _visibility_clause("notifications", scope, int(me["id"]))
        cur.execute(
            "UPDATE notifications SET is_read=1 WHERE brand=? AND id=? AND " + vis_sql,
            tuple([brand, int(nid), *vis_params]),
        )

        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    # ---------------- sending / broadcasting ----------------


    @app.post("/api/notifications/send")
    @login_required
    @role_required("admin", "jefe_estacion")
    def api_notifications_send():
        """Send a notification (admin/jefe_estacion)."""
        me = ctx.get_me()
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        url = (data.get("url") or "").strip()
        mode = (data.get("mode") or "broadcast").strip()

        if not title:
            return jsonify({"error": "title_required"}), 400

        conn = get_conn()
        scope = _station_scope_for_user(conn, me)
        conn.close()
        allowed_station_ids = set(scope.get("station_ids") or [])

        if mode == "user":
            try:
                uid = int(data.get("user_id") or 0)
            except Exception:
                uid = 0
            if uid <= 0:
                return jsonify({"error": "user_id_required"}), 400
            if me.get("role") == "jefe_estacion":
                conn = get_conn(); cur = conn.cursor()
                cur.execute("SELECT station_id FROM users WHERE id=? AND is_active=1", (uid,))
                r = cur.fetchone(); conn.close()
                if not r or (r["station_id"] is None) or int(r["station_id"]) not in allowed_station_ids:
                    return jsonify({"error": "forbidden_target"}), 403
            ctx.notify(uid, None, title, body, url)
            ctx.log_action(me, "send_notification", "notifications", str(uid), {"mode": mode})
            return jsonify({"ok": True})

        if mode in ("station", "roles"):
            try:
                station_id = int(data.get("station_id") or 0)
            except Exception:
                station_id = 0

            if station_id <= 0:
                if me.get("role") == "jefe_estacion" and allowed_station_ids:
                    station_id = list(allowed_station_ids)[0]
                else:
                    return jsonify({"error": "station_id_required"}), 400

            if me.get("role") == "jefe_estacion" and station_id not in allowed_station_ids:
                return jsonify({"error": "forbidden_station"}), 403

            if mode == "station":
                # Station notices should go to the station chief + admins (not all operators).
                ctx.notify_admins_and_station_chiefs(station_id, title, body, url, exclude_user_id=me.get("id"))
                ctx.log_action(me, "send_notification", "notifications", str(station_id), {"mode": mode})
                return jsonify({"ok": True})

            roles = data.get("roles")
            if not isinstance(roles, list) or not roles:
                return jsonify({"error": "roles_required"}), 400
            roles = [str(r).strip() for r in roles if str(r).strip()]
            if not roles:
                return jsonify({"error": "roles_required"}), 400

            ctx.notify_roles(station_id, roles, title, body, url, exclude_user_id=None)
            ctx.log_action(me, "send_notification", "notifications", str(station_id), {"mode": mode, "roles": roles})
            return jsonify({"ok": True})

        # broadcast
        if me.get("role") != "admin":
            return jsonify({"error": "forbidden"}), 403
        ctx.notify(None, None, title, body, url)
        ctx.log_action(me, "send_notification", "notifications", None, {"mode": "broadcast"})
        return jsonify({"ok": True})

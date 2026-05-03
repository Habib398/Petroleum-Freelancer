from __future__ import annotations

from flask import request, jsonify, current_app
from pathlib import Path

from db import get_conn
from services.brand import get_brand


def _clamp_int(v, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except Exception:
        return default
    return max(lo, min(hi, n))


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    # ---------------- Nonconformities (NC) ----------------
    @app.get("/api/capa/nc")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_capa_list_nc():
        me = ctx.get_me() or {}
        brand = get_brand()

        page = _clamp_int(request.args.get("page"), 1, 1, 10_000)
        page_size = _clamp_int(request.args.get("page_size"), 50, 1, 200)
        off = (page - 1) * page_size

        status = (request.args.get("status") or "").strip().lower() or None
        station_id = request.args.get("station_id")

        conn = get_conn(); cur = conn.cursor()

        where = "WHERE brand=?"
        params: list = [brand]

        # station scope
        if me.get("role") != "admin":
            scope = list(ctx.station_scope_ids(me))
            if scope:
                in_clause = ",".join(["?"] * len(scope))
                where += f" AND (station_id IS NULL OR station_id IN ({in_clause}))"
                params.extend(scope)
            else:
                where += " AND station_id IS NULL"
        else:
            if station_id not in (None, "", "null"):
                try:
                    sid = int(station_id)
                    where += " AND station_id=?"
                    params.append(sid)
                except Exception:
                    pass

        if status:
            where += " AND status=?"
            params.append(status)

        cur.execute(f"SELECT COUNT(*) AS c FROM nonconformities {where}", tuple(params))
        total = int((cur.fetchone() or {}).get("c") or 0)

        cur.execute(
            f"""
            SELECT id, brand, station_id, title, description, severity, status, detected_at, detected_by,
                   root_cause, corrective_action, preventive_action, owner_user_id, due_date, closed_at, effectiveness_check
            FROM nonconformities
            {where}
            ORDER BY detected_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, off]),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "total": total, "page": page, "page_size": page_size, "items": items})

    @app.post("/api/capa/nc")
    @login_required
    @role_required("admin")
    def api_capa_create_nc():
        me = ctx.get_me() or {}
        brand = get_brand()
        data = request.get_json(silent=True) or {}

        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "missing_title"}), 400

        station_id = data.get("station_id")
        if station_id in (None, "", "null"):
            station_id = None
        else:
            try:
                station_id = int(station_id)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400

        severity = (data.get("severity") or "media").strip().lower()
        if severity not in {"baja", "media", "alta", "critica"}:
            return jsonify({"ok": False, "error": "invalid_severity"}), 400

        desc = (data.get("description") or "").strip() or None
        owner_user_id = data.get("owner_user_id")
        due_date = (data.get("due_date") or "").strip() or None

        if owner_user_id in (None, "", "null"):
            owner_user_id = None
        else:
            try:
                owner_user_id = int(owner_user_id)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_owner_user_id"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO nonconformities (brand, station_id, title, description, severity, status, detected_by, owner_user_id, due_date)
            VALUES (?,?,?,?,?,'abierta',?,?,?)
            """,
            (brand, station_id, title, desc, severity, me.get("id"), owner_user_id, due_date),
        )
        nc_id = cur.lastrowid
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_create_nc", "nonconformities", str(nc_id), {"station_id": station_id, "severity": severity})
        return jsonify({"ok": True, "id": nc_id})

    @app.get("/api/capa/nc/<int:nc_id>")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_capa_get_nc(nc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM nonconformities WHERE id=? AND brand=?", (nc_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        if me.get("role") != "admin":
            sid = row["station_id"]
            if sid is not None and not ctx.can_access_station(me, int(sid)):
                conn.close()
                return jsonify({"ok": False, "error": "forbidden"}), 403

        cur.execute("SELECT * FROM capa_actions WHERE nc_id=? ORDER BY created_at DESC, id DESC", (nc_id,))
        actions = [dict(r) for r in cur.fetchall()]
        conn.close()
        out = dict(row)
        out["actions"] = actions
        return jsonify({"ok": True, "item": out})

    @app.put("/api/capa/nc/<int:nc_id>")
    @login_required
    @role_required("admin")
    def api_capa_update_nc(nc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        data = request.get_json(silent=True) or {}

        fields = {}
        for k in ["title", "description", "severity", "status", "root_cause", "corrective_action", "preventive_action", "owner_user_id", "due_date", "effectiveness_check"]:
            if k in data:
                fields[k] = data.get(k)

        if "severity" in fields:
            sev = (fields["severity"] or "").strip().lower()
            if sev not in {"baja", "media", "alta", "critica"}:
                return jsonify({"ok": False, "error": "invalid_severity"}), 400
            fields["severity"] = sev

        if "status" in fields:
            st = (fields["status"] or "").strip().lower()
            if st not in {"abierta", "en_progreso", "cerrada"}:
                return jsonify({"ok": False, "error": "invalid_status"}), 400
            fields["status"] = st

        if "owner_user_id" in fields:
            if fields["owner_user_id"] in (None, "", "null"):
                fields["owner_user_id"] = None
            else:
                try:
                    fields["owner_user_id"] = int(fields["owner_user_id"])
                except Exception:
                    return jsonify({"ok": False, "error": "invalid_owner_user_id"}), 400

        if not fields:
            return jsonify({"ok": True})

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM nonconformities WHERE id=? AND brand=?", (nc_id, brand))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        sets = ", ".join([f"{k}=?" for k in fields.keys()])
        cur.execute(f"UPDATE nonconformities SET {sets} WHERE id=? AND brand=?", tuple(list(fields.values()) + [nc_id, brand]))
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_update_nc", "nonconformities", str(nc_id), {"fields": list(fields.keys())})
        return jsonify({"ok": True})

    @app.post("/api/capa/nc/<int:nc_id>/close")
    @login_required
    @role_required("admin")
    def api_capa_close_nc(nc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        data = request.get_json(silent=True) or {}
        eff = (data.get("effectiveness_check") or "").strip() or None

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM nonconformities WHERE id=? AND brand=?", (nc_id, brand))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        cur.execute(
            "UPDATE nonconformities SET status='cerrada', closed_at=CURRENT_TIMESTAMP, effectiveness_check=? WHERE id=? AND brand=?",
            (eff, nc_id, brand),
        )
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_close_nc", "nonconformities", str(nc_id))
        return jsonify({"ok": True})

    # ---------------- CAPA Actions ----------------
    @app.post("/api/capa/nc/<int:nc_id>/actions")
    @login_required
    @role_required("admin")
    def api_capa_add_action(nc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        data = request.get_json(silent=True) or {}

        atype = (data.get("action_type") or "").strip().lower()
        if atype not in {"correctiva", "preventiva", "contencion"}:
            return jsonify({"ok": False, "error": "invalid_action_type"}), 400
        desc = (data.get("description") or "").strip()
        if not desc:
            return jsonify({"ok": False, "error": "missing_description"}), 400

        owner = data.get("owner_user_id")
        if owner in (None, "", "null"):
            owner = None
        else:
            try:
                owner = int(owner)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_owner_user_id"}), 400

        due = (data.get("due_date") or "").strip() or None

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM nonconformities WHERE id=? AND brand=?", (nc_id, brand))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        cur.execute(
            "INSERT INTO capa_actions (nc_id, action_type, description, owner_user_id, due_date) VALUES (?,?,?,?,?)",
            (nc_id, atype, desc, owner, due),
        )
        aid = cur.lastrowid
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_add_action", "capa_actions", str(aid), {"nc_id": nc_id, "action_type": atype})
        return jsonify({"ok": True, "id": aid})

    @app.post("/api/capa/actions/<int:action_id>/evidence")
    @login_required
    @role_required("admin")
    def api_capa_action_evidence(action_id: int):
        """Attach evidence file to an action (pdf/png/jpg)."""
        me = ctx.get_me() or {}
        brand = get_brand()
        f = request.files.get("file")
        if not f or not (f.filename or "").strip():
            return jsonify({"ok": False, "error": "missing_file"}), 400

        allowed_ext = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_magic = {"pdf", "png", "jpg"}
        limit = int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20))

        rel = ctx.save_upload_checked(f, f"capa/evidence", allowed_ext=allowed_ext, allowed_magic=allowed_magic, limit_mb=limit)

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM capa_actions WHERE id=?", (action_id,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        cur.execute("UPDATE capa_actions SET evidence_path=? WHERE id=?", (rel, action_id))
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_action_evidence", "capa_actions", str(action_id), {"file": rel})
        return jsonify({"ok": True, "file_path": rel})

    @app.put("/api/capa/actions/<int:action_id>")
    @login_required
    @role_required("admin")
    def api_capa_update_action(action_id: int):
        me = ctx.get_me() or {}
        data = request.get_json(silent=True) or {}

        fields = {}
        for k in ["description", "owner_user_id", "due_date", "status", "done_at"]:
            if k in data:
                fields[k] = data.get(k)

        if "status" in fields:
            st = (fields["status"] or "").strip().lower()
            if st not in {"pendiente", "en_progreso", "hecha", "cancelada"}:
                return jsonify({"ok": False, "error": "invalid_status"}), 400
            fields["status"] = st
            if st == "hecha" and not fields.get("done_at"):
                fields["done_at"] = ctx.now_iso()

        if "owner_user_id" in fields:
            if fields["owner_user_id"] in (None, "", "null"):
                fields["owner_user_id"] = None
            else:
                try:
                    fields["owner_user_id"] = int(fields["owner_user_id"])
                except Exception:
                    return jsonify({"ok": False, "error": "invalid_owner_user_id"}), 400

        if not fields:
            return jsonify({"ok": True})

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM capa_actions WHERE id=?", (action_id,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        sets = ", ".join([f"{k}=?" for k in fields.keys()])
        cur.execute(f"UPDATE capa_actions SET {sets} WHERE id=?", tuple(list(fields.values()) + [action_id]))
        conn.commit(); conn.close()

        ctx.log_action(me, "capa_update_action", "capa_actions", str(action_id), {"fields": list(fields.keys())})
        return jsonify({"ok": True})

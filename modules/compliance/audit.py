from __future__ import annotations

import io
import csv
import json
from datetime import datetime

from flask import Blueprint, jsonify, request, Response, render_template
from services.brand import get_brand
from db import get_conn


def _parse_meta_blob(blob: str) -> dict:
    try:
        obj = json.loads(blob or "{}")
        return obj if isinstance(obj, dict) else {"value": obj}
    except Exception:
        return {}


def register(app):
    audit_bp = Blueprint("audit", __name__)
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    def _parse_dates():
        start = (request.args.get("start") or "").strip()
        end = (request.args.get("end") or "").strip()
        if start and len(start) == 10:
            start += " 00:00:00"
        if end and len(end) == 10:
            end += " 23:59:59"
        return start or None, end or None

    def _fetch_rows(limit: int | None = None):
        start, end = _parse_dates()
        q = (request.args.get("q") or "").strip()
        action = (request.args.get("action") or "").strip()
        module = (request.args.get("module") or "").strip()
        brand = get_brand()

        sql = """
        SELECT
            al.id,
            al.created_at,
            al.brand,
            al.actor_user_id AS user_id,
            COALESCE(u.username, '') AS username,
            al.action,
            COALESCE(al.entity, '') AS module,
            COALESCE(al.entity_id, '') AS record_id,
            COALESCE(al.meta_json, '') AS details
        FROM audit_log al
        LEFT JOIN users u ON u.id=al.actor_user_id
        WHERE al.brand=?
        """
        params = [brand]

        if start:
            sql += " AND datetime(al.created_at) >= datetime(?)"
            params.append(start)
        if end:
            sql += " AND datetime(al.created_at) <= datetime(?)"
            params.append(end)
        if action:
            sql += " AND al.action=?"
            params.append(action)
        if module:
            sql += " AND COALESCE(al.entity,'')=?"
            params.append(module)
        if q:
            sql += " AND (al.action LIKE ? OR al.entity LIKE ? OR al.entity_id LIKE ? OR al.meta_json LIKE ? OR COALESCE(u.username,'') LIKE ?)"
            like = f"%{q}%"
            params += [like, like, like, like, like]

        sql += " ORDER BY al.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        conn = get_conn(); cur = conn.cursor()
        cur.execute(sql, tuple(params))
        raw = [dict(r) for r in cur.fetchall()]
        conn.close()

        rows = []
        for r in raw:
            meta = _parse_meta_blob(r.get("details") or "")
            rows.append({
                **r,
                "ip_address": meta.get("ip", ""),
                "path": meta.get("path", ""),
                "method": meta.get("method", ""),
                "details_obj": meta,
            })
        return rows

    @audit_bp.get("/api/audit")
    @login_required
    @role_required("admin")
    def api_audit_list():
        limit = min(int(request.args.get("limit") or 200), 1000)
        rows = _fetch_rows(limit=limit)
        return jsonify({"ok": True, "rows": rows})

    @audit_bp.get("/api/audit/export.csv")
    @login_required
    @role_required("admin")
    def api_audit_export_csv():
        rows = _fetch_rows(limit=None)
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["id","created_at","brand","user_id","username","action","module","record_id","ip_address","method","path","details"])
        for r in rows:
            w.writerow([r["id"], r["created_at"], r["brand"], r["user_id"], r["username"], r["action"], r["module"], r["record_id"], r["ip_address"], r["method"], r["path"], r["details"]])

        data = output.getvalue().encode("utf-8")
        filename = f"audit_{get_brand()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(data, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})

    @audit_bp.get("/admin/audit")
    @login_required
    @role_required("admin")
    def page_audit():
        return render_template("admin/audit.html")

    app.register_blueprint(audit_bp)

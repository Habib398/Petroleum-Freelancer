from __future__ import annotations

import datetime
import json
from pathlib import Path

from flask import jsonify, render_template, request, current_app

from db import get_conn
from services.branding import get_normative_config
from services.brand import get_brand


def _today() -> datetime.date:
    return datetime.date.today()


def _parse_date(value: str | None, default: datetime.date) -> datetime.date:
    if not value:
        return default
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return default


def _state_key(prefix: str, brand: str) -> str:
    return f"{prefix}:{(brand or 'consulting').strip().lower()}"


def _get_state(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM system_state WHERE key=?", (key,)).fetchone()
    return (row["value"] if row and row.get("value") is not None else "") or ""


def _set_state(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO system_state (key, value, updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        (key, value),
    )


def _month_start(d: datetime.date) -> datetime.date:
    return d.replace(day=1)


def _add_months(d: datetime.date, months: int) -> datetime.date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    if m == 12:
        last = datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last = datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)
    return datetime.date(y, m, min(d.day, last.day))


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/mod/panel")
    @login_required
    def my_panel_page():
        return render_template("mod/panel.html", me=ctx.get_me())

    @app.get("/api/my/panel")
    @login_required
    def api_my_panel():
        me = ctx.get_me() or {}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        today = _today()
        horizon = today + datetime.timedelta(days=14)
        items: dict = {"cards": [], "lists": {}, "brand": brand, "role": me.get("role")}

        if me.get("role") == "admin":
            # Reuse admin-friendly counters
            cur.execute("SELECT COUNT(*) AS c FROM notifications WHERE brand=? AND is_read=0", (brand,))
            unread = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM submissions WHERE brand=? AND status='submitted'", (brand,))
            submitted = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM payments WHERE brand=? AND status='pending'", (brand,))
            payments_pending = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND status='open'", (brand,))
            alerts_open = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM doc_submissions WHERE brand=? AND review_status='PENDING'", (brand,))
            docs_pending = int(cur.fetchone()["c"] or 0)
            cur.execute(
                "SELECT action, entity, entity_id, created_at FROM audit_log WHERE brand=? ORDER BY id DESC LIMIT 8",
                (brand,),
            )
            items["lists"]["recent_audit"] = [dict(r) for r in cur.fetchall()]
            items["cards"] = [
                {"label": "No leídas", "value": unread, "tone": "ok" if unread == 0 else "warn"},
                {"label": "Entregas enviadas", "value": submitted, "tone": "warn" if submitted else "ok"},
                {"label": "Pagos pendientes", "value": payments_pending, "tone": "warn" if payments_pending else "ok"},
                {"label": "Alertas abiertas", "value": alerts_open, "tone": "bad" if alerts_open else "ok"},
                {"label": "Docs por revisar", "value": docs_pending, "tone": "warn" if docs_pending else "ok"},
            ]
            conn.close()
            return jsonify({"ok": True, **items})

        scope = sorted(list(ctx.station_scope_ids(me)))
        if not scope:
            conn.close()
            return jsonify({"ok": True, **items})

        sid = int(me.get("station_id") or scope[0])
        in_clause = ",".join(["?"] * len(scope))

        cur.execute(
            f"SELECT COUNT(*) AS c FROM notifications WHERE brand=? AND user_id=? AND is_read=0",
            (brand, int(me["id"])),
        )
        unread = int(cur.fetchone()["c"] or 0)

        cur.execute(
            f"""
            SELECT ce.id, ce.title, ce.start_date
            FROM calendar_events ce
            LEFT JOIN submissions s ON s.brand=ce.brand AND s.event_id=ce.id AND s.station_id=? AND s.status IN ('submitted','reviewed','approved')
            WHERE ce.brand=? AND (ce.station_id IS NULL OR ce.station_id IN ({in_clause}))
              AND date(ce.start_date) BETWEEN date(?) AND date(?)
              AND s.id IS NULL
            ORDER BY date(ce.start_date) ASC, ce.id ASC
            LIMIT 12
            """,
            tuple([sid, brand] + scope + [today.isoformat(), horizon.isoformat()]),
        )
        pending_events = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND status='open' AND station_id IN ({in_clause})",
            tuple([brand] + scope),
        )
        alerts_open = int(cur.fetchone()["c"] or 0)

        cur.execute(
            f"SELECT COUNT(*) AS c FROM doc_requirements WHERE brand=? AND status IN ('OPEN','REJECTED','SUBMITTED') AND (station_id IS NULL OR station_id IN ({in_clause}))",
            tuple([brand] + scope),
        )
        docs_pending = int(cur.fetchone()["c"] or 0)

        compliance_expiring = 0
        if brand == "petroleum":
            cur.execute(
                f"SELECT COUNT(*) AS c FROM compliance_records WHERE brand=? AND station_id IN ({in_clause}) AND expiry_date IS NOT NULL AND date(expiry_date) BETWEEN date(?) AND date(?)",
                tuple([brand] + scope + [today.isoformat(), horizon.isoformat()]),
            )
            compliance_expiring = int(cur.fetchone()["c"] or 0)

        cur.execute(
            f"SELECT id, title, body, created_at FROM notifications WHERE brand=? AND user_id=? ORDER BY id DESC LIMIT 8",
            (brand, int(me["id"])),
        )
        my_notifications = [dict(r) for r in cur.fetchall()]

        items["cards"] = [
            {"label": "Pendientes próximos", "value": len(pending_events), "tone": "warn" if pending_events else "ok"},
            {"label": "Alertas abiertas", "value": alerts_open, "tone": "bad" if alerts_open else "ok"},
            {"label": "Docs pendientes", "value": docs_pending, "tone": "warn" if docs_pending else "ok"},
            {"label": "No leídas", "value": unread, "tone": "warn" if unread else "ok"},
            {"label": "Cumplimientos por vencer", "value": compliance_expiring, "tone": "warn" if compliance_expiring else "ok"},
        ]
        items["lists"] = {"pending_events": pending_events, "notifications": my_notifications}
        conn.close()
        return jsonify({"ok": True, **items})

    @app.get("/mod/operational-calendar")
    @login_required
    def operational_calendar_page():
        return render_template("mod/operational_calendar.html", me=ctx.get_me())

    @app.get("/api/operational-calendar")
    @login_required
    def api_operational_calendar():
        me = ctx.get_me() or {}
        brand = get_brand()
        today = _today()
        d_from = _parse_date(request.args.get("from"), today.replace(day=1))
        d_to = _parse_date(request.args.get("to"), _add_months(d_from, 1))
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        conn = get_conn(); cur = conn.cursor()
        scope = [] if me.get("role") == "admin" else sorted(list(ctx.station_scope_ids(me)))
        station_clause = ""
        params_scope: list = []
        if scope:
            q = ",".join(["?"] * len(scope))
            station_clause = f" AND (station_id IS NULL OR station_id IN ({q}))"
            params_scope = scope[:]
        elif me.get("role") != "admin":
            conn.close()
            return jsonify({"ok": True, "items": []})

        items: list[dict] = []

        # Activities / agenda
        cur.execute(
            f"SELECT id, title, start_date, station_id FROM calendar_events WHERE brand=? AND date(start_date) BETWEEN date(?) AND date(?) {station_clause} ORDER BY date(start_date) ASC",
            tuple([brand, d_from.isoformat(), d_to.isoformat()] + params_scope),
        )
        for r in cur.fetchall():
            items.append({"kind": "actividad", "title": r["title"], "date": r["start_date"], "station_id": r["station_id"], "color": "#2563eb", "url": f"/mod/activities/event/{r['id']}"})

        # Document requirements due/open dates
        cur.execute(
            f"SELECT id, title, due_date, station_id, module, status FROM doc_requirements WHERE brand=? AND date(due_date) BETWEEN date(?) AND date(?) {station_clause} ORDER BY date(due_date) ASC",
            tuple([brand, d_from.isoformat(), d_to.isoformat()] + params_scope),
        )
        for r in cur.fetchall():
            mod = (r.get("module") or "doc").upper()
            items.append({"kind": "documento", "title": f"{mod}: {r['title']}", "date": r["due_date"], "station_id": r["station_id"], "status": r.get("status"), "color": "#7c3aed", "url": "/admin/document-center" if me.get("role") == "admin" else "/mod/panel"})

        # Library expirations
        cur.execute(
            f"SELECT document_id, title, expires_at, station_id, module FROM document_versions WHERE brand=? AND expires_at IS NOT NULL AND date(expires_at) BETWEEN date(?) AND date(?) {station_clause} ORDER BY date(expires_at) ASC",
            tuple([brand, d_from.isoformat(), d_to.isoformat()] + params_scope),
        )
        for r in cur.fetchall():
            items.append({"kind": "vencimiento", "title": f"Vence: {r['title']}", "date": r["expires_at"], "station_id": r["station_id"], "color": "#ea580c", "url": "/admin/document-center"})

        # Petroleum compliance expirations
        if brand == "petroleum":
            cur.execute(
                f"SELECT cr.item_code, ci.title, cr.expiry_date, cr.station_id FROM compliance_records cr JOIN compliance_items ci ON ci.code=cr.item_code WHERE cr.brand=? AND cr.expiry_date IS NOT NULL AND date(cr.expiry_date) BETWEEN date(?) AND date(?) {'AND cr.station_id IN (' + ','.join(['?']*len(scope)) + ')' if scope else ''} ORDER BY date(cr.expiry_date) ASC",
                tuple([brand, d_from.isoformat(), d_to.isoformat()] + (scope[:] if scope else [])),
            )
            docs_cfg = get_normative_config('petroleum')
            for r in cur.fetchall():
                code = (r['item_code'] or '').strip().lower()
                title = (docs_cfg.get(code) or {}).get('title') or r['title']
                items.append({"kind": "cumplimiento", "title": f"Cumplimiento: {title}", "date": r['expiry_date'], "station_id": r['station_id'], "color": "#dc2626", "url": "/petroleum/cumplimiento"})

        conn.close()
        return jsonify({"ok": True, "items": items[:600], "range": {"from": d_from.isoformat(), "to": d_to.isoformat()}})

    @app.get("/api/admin/settings/deadlines")
    @login_required
    @role_required("admin")
    def api_admin_settings_deadlines_get():
        brand = get_brand()
        conn = get_conn()
        data = {
            "activity_lock_date": _get_state(conn, _state_key("activity_lock_date", brand)),
            "doc_capture_lock_date": _get_state(conn, _state_key("doc_capture_lock_date", brand)),
        }
        conn.close()
        return jsonify({"ok": True, **data})

    @app.post("/api/admin/settings/deadlines")
    @login_required
    @role_required("admin")
    def api_admin_settings_deadlines_set():
        brand = get_brand()
        payload = request.get_json(silent=True) or {}
        activity_lock_date = (payload.get("activity_lock_date") or "").strip()
        doc_capture_lock_date = (payload.get("doc_capture_lock_date") or "").strip()
        for raw in [activity_lock_date, doc_capture_lock_date]:
            if raw:
                try:
                    datetime.date.fromisoformat(raw[:10])
                except Exception:
                    return jsonify({"ok": False, "error": "invalid_date"}), 400
        conn = get_conn()
        _set_state(conn, _state_key("activity_lock_date", brand), activity_lock_date)
        _set_state(conn, _state_key("doc_capture_lock_date", brand), doc_capture_lock_date)
        conn.commit(); conn.close()
        ctx.log_action(ctx.get_me(), "update_deadline_settings", "system_state", brand, {"activity_lock_date": activity_lock_date, "doc_capture_lock_date": doc_capture_lock_date})
        return jsonify({"ok": True})

    @app.get("/api/admin/signatures")
    @login_required
    @role_required("admin", "jefe_estacion", "auditor")
    def api_admin_signatures():
        entity = (request.args.get("entity") or "").strip()
        entity_id = (request.args.get("entity_id") or "").strip()
        if not entity or not entity_id:
            return jsonify({"ok": False, "error": "missing_params"}), 400
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT id, entity, entity_id, action, signer_user_id, signer_name, signer_role, signer_ip, details_json, signed_at FROM internal_signatures WHERE brand=? AND entity=? AND entity_id=? ORDER BY id DESC LIMIT 100",
            (get_brand(), entity, entity_id),
        )
        rows = []
        for r in cur.fetchall():
            item = dict(r)
            try:
                item["details"] = json.loads(item.get("details_json") or "{}") or {}
            except Exception:
                item["details"] = {}
            rows.append(item)
        conn.close()
        return jsonify({"ok": True, "rows": rows})

    @app.get("/api/admin/semaphore")
    @login_required
    @role_required("admin")
    def api_admin_semaphore():
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY code ASC, id ASC", (brand,))
        stations = [dict(r) for r in cur.fetchall()]
        rows = []
        for st in stations:
            sid = int(st["id"])
            cur.execute("SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND station_id=? AND status='open'", (brand, sid))
            alerts_open = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM payments WHERE brand=? AND station_id=? AND status='pending'", (brand, sid))
            payments_pending = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM doc_requirements WHERE brand=? AND station_id=? AND status IN ('OPEN','REJECTED','SUBMITTED')", (brand, sid))
            docs_pending = int(cur.fetchone()["c"] or 0)
            compliance_expiring = 0
            if brand == 'petroleum':
                cur.execute("SELECT COUNT(*) AS c FROM compliance_records WHERE brand=? AND station_id=? AND expiry_date IS NOT NULL AND date(expiry_date) <= date(?)", (brand, sid, (_today() + datetime.timedelta(days=30)).isoformat()))
                compliance_expiring = int(cur.fetchone()["c"] or 0)
            score = alerts_open * 3 + payments_pending * 4 + docs_pending * 4 + compliance_expiring * 5
            color = 'green' if score == 0 else 'yellow' if score <= 8 else 'red'
            rows.append({**st, 'alerts_open': alerts_open, 'payments_pending': payments_pending, 'docs_pending': docs_pending, 'compliance_expiring': compliance_expiring, 'score': score, 'color': color})
        conn.close()
        return jsonify({"ok": True, "rows": rows})

    @app.get("/api/admin/kpi-trends")
    @login_required
    @role_required("admin")
    def api_admin_kpi_trends():
        brand = get_brand()
        today = _today().replace(day=1)
        conn = get_conn(); cur = conn.cursor()
        rows = []
        for i in range(5, -1, -1):
            m0 = _add_months(today, -i)
            m1 = _add_months(m0, 1)
            cur.execute("SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND date(created_at)>=date(?) AND date(created_at)<date(?)", (brand, m0.isoformat(), m1.isoformat()))
            alerts = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM submissions WHERE brand=? AND date(created_at)>=date(?) AND date(created_at)<date(?) AND status IN ('approved','reviewed','submitted')", (brand, m0.isoformat(), m1.isoformat()))
            submissions = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM doc_submissions WHERE brand=? AND date(submitted_at)>=date(?) AND date(submitted_at)<date(?)", (brand, m0.isoformat(), m1.isoformat()))
            docs = int(cur.fetchone()["c"] or 0)
            rows.append({"month": m0.strftime("%Y-%m"), "alerts": alerts, "submissions": submissions, "docs": docs})
        conn.close()
        return jsonify({"ok": True, "rows": rows})

    @app.get("/mod/evidencias")
    @login_required
    def evidence_gallery_page():
        return render_template("mod/evidencias.html", me=ctx.get_me())

    @app.post("/api/evidence/photos")
    @login_required
    def api_evidence_photos_upload():
        me = ctx.get_me() or {}
        entity = (request.form.get("entity") or "general").strip().lower()
        entity_id = (request.form.get("entity_id") or "0").strip() or "0"
        caption = (request.form.get("caption") or "").strip()
        station_id_raw = (request.form.get("station_id") or "").strip()
        station_id = None
        if station_id_raw:
            try:
                station_id = int(station_id_raw)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        elif me.get("station_id"):
            station_id = int(me.get("station_id"))
        if me.get("role") != "admin" and station_id is not None and not ctx.can_access_station(me, int(station_id)):
            return jsonify({"ok": False, "error": "forbidden_station"}), 403

        files = request.files.getlist("files") or request.files.getlist("files[]")
        if not files:
            f = request.files.get("file")
            if f:
                files = [f]
        if not files:
            return jsonify({"ok": False, "error": "missing_files"}), 400

        out = []
        conn = get_conn(); cur = conn.cursor()
        for f in files[:20]:
            if not f or not (f.filename or "").strip():
                continue
            rel = ctx.save_upload_checked(
                f,
                subdir=f"evidence_photos/{station_id or 'global'}/{entity}",
                allowed_ext={".png", ".jpg", ".jpeg", ".webp"},
                allowed_magic={"png", "jpg", "webp"},
                limit_mb=15,
            )
            cur.execute(
                "INSERT INTO evidence_photos (brand, station_id, entity, entity_id, file_path, caption, uploaded_by) VALUES (?,?,?,?,?,?,?)",
                (get_brand(), station_id, entity, entity_id, rel, caption or None, me.get("id")),
            )
            out.append({"id": cur.lastrowid, "file_path": rel})
        conn.commit(); conn.close()
        ctx.log_action(me, "upload_evidence_photos", "evidence_photos", entity_id, {"entity": entity, "count": len(out), "station_id": station_id})
        ctx.sign_entity(me, entity, entity_id, "evidence_photos_uploaded", {"count": len(out), "station_id": station_id})
        return jsonify({"ok": True, "items": out})

    @app.get("/api/evidence/photos")
    @login_required
    def api_evidence_photos_list():
        me = ctx.get_me() or {}
        entity = (request.args.get("entity") or "").strip().lower()
        entity_id = (request.args.get("entity_id") or "").strip()
        station_id = (request.args.get("station_id") or "").strip()
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        where = ["brand=?"]
        params: list = [brand]
        if entity:
            where.append("entity=?")
            params.append(entity)
        if entity_id:
            where.append("entity_id=?")
            params.append(entity_id)
        if station_id:
            try:
                sid = int(station_id)
            except Exception:
                conn.close()
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
            where.append("station_id=?")
            params.append(sid)
        if me.get("role") != "admin":
            scope = sorted(list(ctx.station_scope_ids(me)))
            if scope:
                q = ",".join(["?"] * len(scope))
                where.append(f"(station_id IS NULL OR station_id IN ({q}))")
                params.extend(scope)
            else:
                where.append("station_id IS NULL")
        cur.execute(
            "SELECT id, station_id, entity, entity_id, file_path, caption, uploaded_by, created_at FROM evidence_photos WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 200",
            tuple(params),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.get("/admin/reports/print/consolidated")
    @login_required
    @role_required("admin")
    def admin_reports_print_consolidated():
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY code ASC", (brand,))
        stations = [dict(r) for r in cur.fetchall()]
        rows = []
        for st in stations:
            sid = int(st["id"])
            cur.execute("SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND station_id=? AND status='open'", (brand, sid))
            alerts_open = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM maintenance WHERE brand=? AND station_id=?", (brand, sid))
            maintenance_count = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM payments WHERE brand=? AND station_id=? AND status='pending'", (brand, sid))
            payments_pending = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM doc_requirements WHERE brand=? AND station_id=? AND status IN ('OPEN','REJECTED','SUBMITTED')", (brand, sid))
            docs_pending = int(cur.fetchone()["c"] or 0)
            rows.append({**st, "alerts_open": alerts_open, "maintenance_count": maintenance_count, "payments_pending": payments_pending, "docs_pending": docs_pending})
        conn.close()
        return render_template("admin/print_consolidated.html", me=ctx.get_me(), brand=brand, rows=rows, generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

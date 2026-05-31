from __future__ import annotations

import os
import base64
import datetime
import difflib
import io
import json
from pathlib import Path

try:
    import qrcode
except Exception:  # pragma: no cover
    qrcode = None

from flask import current_app, jsonify, render_template, request, send_file

from db import get_conn
from services.brand import get_brand
from services.storage import get_storage
from services.branding import DEFAULT_BRAND_SETTINGS, get_branding_settings, set_branding_settings
from services.corrections import create_correction_task
from services.outbound import send_email_delivery

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _quote_recipients() -> list[str]:
    raw = os.environ.get('PUBLIC_QUOTE_RECIPIENTS') or 'usiel54@hotmail.com,misaelsainz9@gmail.com'
    return [item.strip() for item in str(raw).split(',') if item.strip()]


def _extract_pdf_text(abs_path: Path) -> tuple[str, int]:
    if not abs_path.exists() or fitz is None:
        return "", 0
    try:
        doc = fitz.open(abs_path)
        pages = len(doc)
        text_parts = []
        for page in doc[: min(8, pages)]:
            try:
                text_parts.append(page.get_text("text"))
            except Exception:
                pass
        doc.close()
        return "\n".join(text_parts), pages
    except Exception:
        return "", 0


def _station_scope_filter(ctx, me: dict, station_id):
    if me.get("role") == "admin":
        return True
    if station_id is None:
        return True
    return ctx.can_access_station(me, int(station_id))


_PLACEHOLDER_QR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sotq3sAAAAASUVORK5CYII="
)


def _qr_png_bytes(data: str) -> bytes:
    """Return a QR PNG when qrcode is available, otherwise a tiny PNG placeholder.

    This keeps the whole app bootable even when the optional qrcode dependency
    has not been installed in a local environment yet.
    """
    if qrcode is None:
        return _PLACEHOLDER_QR_PNG
    img = qrcode.make(data or "")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio.getvalue()


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/admin/setup-wizard")
    @login_required
    @role_required("admin")
    def setup_wizard_page():
        return render_template("admin/setup_wizard.html")

    @app.get("/api/admin/setup-wizard")
    @login_required
    @role_required("admin")
    def api_setup_wizard_get():
        return jsonify({
            "ok": True,
            "brands": {
                "consulting": get_branding_settings("consulting"),
                "petroleum": get_branding_settings("petroleum"),
            },
            "runtime_scheduler_enabled": current_app.extensions.get("runtime_scheduler_started", False),
        })

    @app.post("/api/admin/setup-wizard")
    @login_required
    @role_required("admin")
    def api_setup_wizard_set():
        payload = request.get_json(silent=True) or {}
        brand = (payload.get("brand") or "consulting").strip().lower()
        data = payload.get("settings") or {}
        allowed = set(DEFAULT_BRAND_SETTINGS.get(brand, {}).keys())
        clean = {k: str(v or "") for k, v in data.items() if k in allowed}
        set_branding_settings(brand, clean)
        ctx.log_action(ctx.get_me(), "update_branding", "branding_settings", brand, clean)
        return jsonify({"ok": True, "settings": get_branding_settings(brand)})

    @app.post("/api/admin/setup-wizard/test-mail")
    @login_required
    @role_required("admin")
    def api_setup_wizard_test_mail():
        payload = request.get_json(silent=True) or {}
        brand = (payload.get("brand") or "consulting").strip().lower()
        recipients = _quote_recipients()
        if not recipients:
            return jsonify({"ok": False, "error": "missing_recipients", "message": "No hay destinatarios configurados para cotizaciones."}), 400

        subject = f"Prueba de correo saliente · {brand.title()} · Work Log"
        text_body = (
            "Esta es una prueba manual del correo saliente configurado en Work Log.\n\n"
            f"Marca: {brand}\n"
            f"Destinatarios: {', '.join(recipients)}\n\n"
            "Si recibes este correo, la salida de cotizaciones y avisos ya puede validarse desde el panel admin."
        )
        html_body = f"""
        <div style=\"font-family:Arial,Helvetica,sans-serif;background:#f4f7fb;padding:24px;\">
          <div style=\"max-width:640px;margin:0 auto;background:#ffffff;border-radius:18px;padding:28px;border:1px solid #e5e7eb;\">
            <div style=\"font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#64748b;margin-bottom:10px;\">Work Log · prueba de correo</div>
            <h1 style=\"margin:0 0 12px;font-size:24px;color:#0f172a;\">Correo saliente operativo</h1>
            <p style=\"margin:0 0 12px;color:#334155;line-height:1.6;\">Esta prueba fue enviada desde <strong>Configuración → Probar correo</strong> para validar la salida automática de cotizaciones y notificaciones.</p>
            <div style=\"margin-top:14px;padding:16px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;\">
              <div><strong>Marca:</strong> {brand.title()}</div>
              <div><strong>Destinatarios:</strong> {', '.join(recipients)}</div>
            </div>
          </div>
        </div>
        """
        ok, detail = send_email_delivery(recipients, subject, text_body, brand=brand, html_body=html_body)
        code = 200 if ok else 400
        return jsonify({
            "ok": ok,
            "detail": detail,
            "brand": brand,
            "recipients": recipients,
            "message": "Prueba enviada correctamente." if ok else "No se pudo enviar la prueba. Revisa proveedor y credenciales.",
        }), code

    @app.post("/api/admin/branding/logo")
    @login_required
    @role_required("admin")
    def api_branding_logo_upload():
        brand = (request.form.get("brand") or "consulting").strip().lower()
        variant = (request.form.get("variant") or "logo_path").strip()
        if variant not in {"logo_path", "logo_square_path"}:
            return jsonify({"ok": False, "error": "invalid_variant"}), 400
        f = request.files.get("file")
        if not f or not (f.filename or "").strip():
            return jsonify({"ok": False, "error": "missing_file"}), 400
        rel = ctx.save_upload_checked(f, f"branding/{brand}", allowed_ext={".png", ".jpg", ".jpeg", ".webp"}, limit_mb=10, allowed_magic={"png", "jpg"})
        set_branding_settings(brand, {variant: rel})
        return jsonify({"ok": True, "file_path": rel, "settings": get_branding_settings(brand)})

    @app.get("/mod/help-center")
    @login_required
    def help_center_page():
        return render_template("mod/help_center.html")

    @app.get("/api/help-center")
    @login_required
    def api_help_center():
        brand = get_brand()
        q = (request.args.get("q") or "").strip().lower()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT id, category, title, body, is_featured, sort_order FROM help_articles WHERE brand=? ORDER BY is_featured DESC, sort_order ASC, id ASC",
            (brand,),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        if q:
            items = [it for it in items if q in ((it.get("title") or "") + " " + (it.get("body") or "") + " " + (it.get("category") or "")).lower()]
        return jsonify({"ok": True, "items": items, "branding": get_branding_settings(brand)})

    _INCIDENT_STATUSES = {"pendiente", "leido", "atendido", "reportado"}
    _INCIDENT_OPERATIVE_ROLES = ("operador", "jefe_estacion")

    @app.get("/mod/incidents")
    @login_required
    @role_required(*_INCIDENT_OPERATIVE_ROLES)
    def incidents_page():
        return render_template("mod/incidents.html")

    @app.get("/api/incidents")
    @login_required
    @role_required(*_INCIDENT_OPERATIVE_ROLES)
    def api_incidents_list():
        me = ctx.get_me() or {}
        brand = get_brand()
        status = (request.args.get("status") or "").strip().lower()
        conn = get_conn(); cur = conn.cursor()
        params = [brand]
        sql = (
            "SELECT i.*, s.code AS station_code, s.name AS station_name, "
            "u.username AS assigned_name, c.username AS created_by_name, "
            "ack.username AS acknowledged_by_name "
            "FROM incident_logs i "
            "LEFT JOIN stations s ON s.id=i.station_id "
            "LEFT JOIN users u ON u.id=i.assigned_to "
            "LEFT JOIN users c ON c.id=i.created_by "
            "LEFT JOIN users ack ON ack.id=i.acknowledged_by "
            "WHERE i.brand=?"
        )
        if status in _INCIDENT_STATUSES:
            sql += " AND i.status=?"
            params.append(status)
        scope = sorted(list(ctx.station_scope_ids(me)))
        if scope:
            sql += " AND (i.station_id IS NULL OR i.station_id IN (%s))" % ",".join(["?"] * len(scope))
            params.extend(scope)
        else:
            sql += " AND i.station_id IS NULL"
        sql += (
            " ORDER BY CASE i.status WHEN 'pendiente' THEN 0 WHEN 'leido' THEN 1 ELSE 2 END,"
            " i.id DESC LIMIT 300"
        )
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.get("/api/incidents/pending-count")
    @login_required
    @role_required(*_INCIDENT_OPERATIVE_ROLES)
    def api_incidents_pending_count():
        me = ctx.get_me() or {}
        brand = get_brand()
        scope = sorted(list(ctx.station_scope_ids(me)))
        conn = get_conn(); cur = conn.cursor()
        sql = "SELECT COUNT(*) AS c FROM incident_logs WHERE brand=? AND status='pendiente'"
        params = [brand]
        if scope:
            sql += " AND (station_id IS NULL OR station_id IN (%s))" % ",".join(["?"] * len(scope))
            params.extend(scope)
        else:
            sql += " AND station_id IS NULL"
        cur.execute(sql, tuple(params))
        count = int(cur.fetchone()["c"] or 0)
        conn.close()
        return jsonify({"ok": True, "count": count})

    @app.post("/api/incidents")
    @login_required
    @role_required(*_INCIDENT_OPERATIVE_ROLES)
    def api_incidents_create():
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "missing_title"}), 400
        station_id = payload.get("station_id")
        if station_id not in (None, "", "null"):
            try:
                station_id = int(station_id)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
            if not _station_scope_filter(ctx, me, station_id):
                return jsonify({"ok": False, "error": "forbidden_station"}), 403
        else:
            station_id = int(me.get("station_id")) if me.get("station_id") else None
        severity = (payload.get("severity") or "medium").strip().lower()
        if severity not in {"low", "medium", "high", "critical"}:
            severity = "medium"
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO incident_logs (brand, station_id, module, category, severity, status, title, description, created_by, updated_at) "
            "VALUES (?,?,?,?,?,'pendiente',?,?,?,CURRENT_TIMESTAMP)",
            (
                brand, station_id, (payload.get("module") or "general").strip(),
                (payload.get("category") or "general").strip(), severity,
                title, (payload.get("description") or "").strip() or None, me.get("id"),
            ),
        )
        incident_id = int(cur.lastrowid)
        conn.commit(); conn.close()
        ctx.log_action(me, "create_incident", "incident_logs", str(incident_id), {"station_id": station_id, "severity": severity, "status": "pendiente"})
        if station_id:
            ctx.notify_station_chiefs(
                int(station_id),
                "Nueva incidencia pendiente",
                title[:180],
                "/mod/incidents",
                exclude_user_id=me.get("id"),
                ntype="incident",
                brand=brand,
            )
        return jsonify({"ok": True, "id": incident_id})

    @app.patch("/api/incidents/<int:incident_id>")
    @login_required
    @role_required("jefe_estacion")
    def api_incidents_update(incident_id: int):
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM incident_logs WHERE id=? AND brand=?", (incident_id, get_brand()))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({"ok": False, "error": "not_found"}), 404
        if not _station_scope_filter(ctx, me, row.get("station_id")):
            conn.close(); return jsonify({"ok": False, "error": "forbidden_station"}), 403
        prev_status = (row.get("status") or "pendiente").strip().lower()
        new_status = (payload.get("status") or prev_status).strip().lower()
        if new_status not in _INCIDENT_STATUSES:
            new_status = prev_status
        # acknowledged_*: se fija la primera vez que la incidencia sale de "pendiente".
        ack_by = row.get("acknowledged_by")
        ack_at = row.get("acknowledged_at")
        if new_status != "pendiente" and not ack_by:
            ack_by = me.get("id")
            ack_at = ctx.now_iso()
        # resolved_*: se fija la primera vez que la incidencia entra a un estado terminal.
        resolved_by = row.get("resolved_by")
        resolved_at = row.get("resolved_at")
        if new_status in ("atendido", "reportado") and not resolved_by:
            resolved_by = me.get("id")
            resolved_at = ctx.now_iso()
        cur.execute(
            "UPDATE incident_logs SET status=?, acknowledged_by=?, acknowledged_at=?, "
            "resolved_by=?, resolved_at=?, updated_at=CURRENT_TIMESTAMP, "
            "description=?, title=?, severity=? WHERE id=? AND brand=?",
            (
                new_status, ack_by, ack_at, resolved_by, resolved_at,
                (payload.get("description") or row.get("description") or "").strip() or None,
                (payload.get("title") or row.get("title") or "").strip(),
                (payload.get("severity") or row.get("severity") or "medium").strip().lower(),
                incident_id, get_brand(),
            ),
        )
        conn.commit(); conn.close()
        ctx.log_action(me, "update_incident", "incident_logs", str(incident_id), {"prev_status": prev_status, "status": new_status})
        return jsonify({"ok": True})

    @app.get("/mod/corrections")
    @login_required
    def corrections_page():
        return render_template("mod/corrections.html")

    @app.get("/api/corrections")
    @login_required
    def api_corrections_list():
        me = ctx.get_me() or {}
        brand = get_brand()
        status = (request.args.get("status") or "").strip().lower()
        conn = get_conn(); cur = conn.cursor()
        params = [brand]
        sql = (
            "SELECT c.*, s.code AS station_code, s.name AS station_name, u.username AS assigned_name "
            "FROM correction_tasks c LEFT JOIN stations s ON s.id=c.station_id LEFT JOIN users u ON u.id=c.assigned_to WHERE c.brand=?"
        )
        if status in {"open", "in_progress", "done", "cancelled"}:
            sql += " AND c.status=?"
            params.append(status)
        if me.get("role") != "admin":
            scope = sorted(list(ctx.station_scope_ids(me)))
            if scope:
                sql += " AND (c.station_id IS NULL OR c.station_id IN (%s) OR c.assigned_to=?)" % ",".join(["?"] * len(scope))
                params.extend(scope)
                params.append(int(me["id"]))
            else:
                sql += " AND c.assigned_to=?"
                params.append(int(me["id"]))
        sql += " ORDER BY CASE c.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, COALESCE(c.due_date,'9999-12-31') ASC, c.id DESC LIMIT 400"
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.post("/api/corrections")
    @login_required
    def api_corrections_create():
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "missing_title"}), 400
        station_id = payload.get("station_id") or me.get("station_id")
        if station_id not in (None, "", "null"):
            try:
                station_id = int(station_id)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
            if not _station_scope_filter(ctx, me, station_id):
                return jsonify({"ok": False, "error": "forbidden_station"}), 403
        else:
            station_id = None
        assigned_to = payload.get("assigned_to")
        if assigned_to not in (None, ""):
            try:
                assigned_to = int(assigned_to)
            except Exception:
                assigned_to = None
        task_id = create_correction_task(
            ctx, me, brand=get_brand(), title=title, description=(payload.get("description") or "").strip(), station_id=station_id,
            module=(payload.get("module") or "general").strip(), related_entity=(payload.get("related_entity") or "manual").strip(),
            related_entity_id=str(payload.get("related_entity_id") or "").strip(), assigned_to=assigned_to, due_days=int(payload.get("due_days") or 3),
            priority=(payload.get("priority") or "medium").strip(), source_status=(payload.get("source_status") or "manual").strip(),
        )
        return jsonify({"ok": True, "id": task_id})

    @app.patch("/api/corrections/<int:task_id>")
    @login_required
    def api_corrections_update(task_id: int):
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM correction_tasks WHERE id=? AND brand=?", (task_id, get_brand()))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({"ok": False, "error": "not_found"}), 404
        if me.get("role") != "admin" and int(row.get("assigned_to") or 0) not in {int(me.get("id") or 0)} and not _station_scope_filter(ctx, me, row.get("station_id")):
            conn.close(); return jsonify({"ok": False, "error": "forbidden_station"}), 403
        status = (payload.get("status") or row.get("status") or "open").strip().lower()
        if status not in {"open", "in_progress", "done", "cancelled"}:
            status = row.get("status") or "open"
        completed_at = ctx.now_iso() if status == "done" else None
        cur.execute(
            "UPDATE correction_tasks SET status=?, title=?, description=?, due_date=?, priority=?, assigned_to=?, completed_by=?, completed_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND brand=?",
            (
                status,
                (payload.get("title") or row.get("title") or "").strip(),
                (payload.get("description") or row.get("description") or "").strip() or None,
                (payload.get("due_date") or row.get("due_date") or "").strip() or None,
                (payload.get("priority") or row.get("priority") or "medium").strip(),
                int(payload.get("assigned_to")) if payload.get("assigned_to") not in (None, "") else row.get("assigned_to"),
                me.get("id") if status == "done" else None,
                completed_at,
                task_id,
                get_brand(),
            ),
        )
        conn.commit(); conn.close()
        ctx.log_action(me, "update_correction_task", "correction_tasks", str(task_id), {"status": status})
        return jsonify({"ok": True})

    @app.get("/mod/signature-pad")
    @login_required
    def signature_pad_page():
        return render_template("mod/signature_pad.html")

    @app.post("/api/signatures/drawn")
    @login_required
    def api_signatures_drawn_save():
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or {}
        image_data = (payload.get("image_data") or "").strip()
        entity = (payload.get("entity") or "general").strip()
        entity_id = str(payload.get("entity_id") or "0").strip() or "0"
        action = (payload.get("action") or "signed").strip()
        if not image_data.startswith("data:image/png;base64,"):
            return jsonify({"ok": False, "error": "invalid_image_data"}), 400
        try:
            raw = base64.b64decode(image_data.split(",", 1)[1])
        except Exception:
            return jsonify({"ok": False, "error": "invalid_image_data"}), 400
        if len(raw) < 100:
            return jsonify({"ok": False, "error": "empty_signature"}), 400
        brand = get_brand()
        subdir = Path(brand) / "drawn_signatures"
        fname = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{me.get('id') or 'anon'}.png"
        rel = str(subdir / fname).replace("\\", "/")
        get_storage().save_bytes(raw, rel, content_type="image/png")
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO drawn_signatures (brand, entity, entity_id, action, signer_user_id, file_path) VALUES (?,?,?,?,?,?)",
            (brand, entity, entity_id, action, me.get("id"), rel),
        )
        sid = int(cur.lastrowid)
        conn.commit(); conn.close()
        ctx.sign_entity(me, entity, entity_id, action, {"drawing_path": rel}, brand=brand)
        return jsonify({"ok": True, "id": sid, "file_path": rel, "url": f"/uploads/{rel}"})

    @app.get("/api/signatures/drawn")
    @login_required
    def api_signatures_drawn_list():
        entity = (request.args.get("entity") or "general").strip()
        entity_id = str(request.args.get("entity_id") or "0").strip() or "0"
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, action, file_path, created_at, signer_user_id FROM drawn_signatures WHERE brand=? AND entity=? AND entity_id=? ORDER BY id DESC", (get_brand(), entity, entity_id))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.get("/api/qr/station/<int:station_id>.png")
    @login_required
    def api_qr_station(station_id: int):
        me = ctx.get_me() or {}
        if not _station_scope_filter(ctx, me, station_id):
            return jsonify({"ok": False, "error": "forbidden_station"}), 403
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE id=? AND brand=?", (station_id, get_brand()))
        st = cur.fetchone(); conn.close()
        if not st:
            return jsonify({"ok": False, "error": "not_found"}), 404
        target = f"{request.url_root.rstrip('/')}/mod/panel?station_id={station_id}"
        return send_file(io.BytesIO(_qr_png_bytes(target)), mimetype="image/png", download_name=f"qr_station_{station_id}.png")

    @app.get("/api/qr/document/<int:doc_id>.png")
    @login_required
    def api_qr_document(doc_id: int):
        me = ctx.get_me() or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, station_id, title FROM documents WHERE id=? AND brand=?", (doc_id, get_brand()))
        row = cur.fetchone(); conn.close()
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not _station_scope_filter(ctx, me, row.get("station_id")):
            return jsonify({"ok": False, "error": "forbidden_station"}), 403
        target = f"{request.url_root.rstrip('/')}/admin/document-center?doc_id={doc_id}"
        return send_file(io.BytesIO(_qr_png_bytes(target)), mimetype="image/png", download_name=f"qr_document_{doc_id}.png")

    @app.get("/admin/docs/compare")
    @login_required
    @role_required("admin")
    def docs_compare_page():
        return render_template("admin/docs_compare.html")

    @app.get("/api/docs/compare")
    @login_required
    @role_required("admin", "jefe_estacion", "auditor")
    def api_docs_compare():
        group_key = (request.args.get("group_key") or "").strip()
        left = (request.args.get("left") or "").strip()
        right = (request.args.get("right") or "").strip()
        if not (group_key and left and right):
            return jsonify({"ok": False, "error": "missing_params"}), 400
        try:
            left_v = int(left); right_v = int(right)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_version"}), 400
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT id, version_no, document_id, file_path, title, module, section, station_id, created_at, expires_at, status FROM document_versions WHERE brand=? AND doc_group_key=? AND version_no IN (?,?) ORDER BY version_no ASC",
            (get_brand(), group_key, left_v, right_v),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if len(rows) != 2:
            return jsonify({"ok": False, "error": "versions_not_found"}), 404
        me = ctx.get_me() or {}
        for r in rows:
            if not _station_scope_filter(ctx, me, r.get("station_id")):
                return jsonify({"ok": False, "error": "forbidden_station"}), 403
        a, b = rows[0], rows[1]
        upload_root = current_app.extensions["ctx"].upload_dir
        a_path = upload_root / a["file_path"]
        b_path = upload_root / b["file_path"]
        a_text, a_pages = _extract_pdf_text(a_path)
        b_text, b_pages = _extract_pdf_text(b_path)
        ratio = difflib.SequenceMatcher(None, a_text[:20000], b_text[:20000]).ratio() if (a_text or b_text) else 1.0
        diff_lines = list(difflib.unified_diff((a_text[:4000] or "").splitlines(), (b_text[:4000] or "").splitlines(), fromfile=f"v{a['version_no']}", tofile=f"v{b['version_no']}", n=1))[:120]
        same_size = None
        try:
            same_size = a_path.stat().st_size == b_path.stat().st_size
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "left": {**a, "pages": a_pages, "size": (a_path.stat().st_size if a_path.exists() else 0)},
            "right": {**b, "pages": b_pages, "size": (b_path.stat().st_size if b_path.exists() else 0)},
            "summary": {
                "text_similarity": round(float(ratio), 4),
                "same_size": same_size,
                "title_changed": (a.get("title") or "") != (b.get("title") or ""),
                "status_changed": (a.get("status") or "") != (b.get("status") or ""),
                "expires_changed": (a.get("expires_at") or "") != (b.get("expires_at") or ""),
            },
            "diff_preview": "\n".join(diff_lines),
        })

    @app.get("/api/admin/dashboard/charts")
    @login_required
    @role_required("admin")
    def api_admin_dashboard_charts():
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY code ASC", (brand,))
        stations = [dict(r) for r in cur.fetchall()]
        station_breakdown = []
        for st in stations[:20]:
            sid = int(st["id"])
            cur.execute("SELECT COUNT(*) AS c FROM alerts WHERE brand=? AND station_id=? AND status='open'", (brand, sid))
            alerts = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM correction_tasks WHERE brand=? AND station_id=? AND status IN ('open','in_progress')", (brand, sid))
            tasks = int(cur.fetchone()["c"] or 0)
            station_breakdown.append({"station": st["code"], "alerts": alerts, "tasks": tasks})
        cur.execute("SELECT status, COUNT(*) AS c FROM correction_tasks WHERE brand=? GROUP BY status", (brand,))
        task_status = {r["status"]: int(r["c"] or 0) for r in cur.fetchall()}
        conn.close()
        return jsonify({"ok": True, "station_breakdown": station_breakdown, "task_status": task_status})

from __future__ import annotations

import os
import datetime
import secrets
from pathlib import Path

from flask import jsonify, request, session, render_template, redirect
from werkzeug.utils import secure_filename

from db import get_conn, get_user
from services.branding import NORMATIVE_DEFAULTS, get_normative_config, get_normative_items
from modules.auth.auth import login_required, role_required


ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg"}


def _brand() -> str:
    return session.get("brand", "consulting")


def _is_allowed(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in ALLOWED_EXTS


def _detect_kind(data: bytes) -> str | None:
    # Magic bytes detection (lightweight)
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _ensure_brand_petroleum():
    if _brand() != "petroleum":
        return jsonify({"ok": False, "error": "forbidden", "message": "Solo disponible en Petroleum"}), 403
    return None


def register(app):
    ctx = app.extensions["ctx"]
    # --- UI ---
    @app.get("/petroleum/cumplimiento")
    @app.get("/petroleum/normativas")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def petroleum_cumplimiento():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        return render_template("petroleum_cumplimiento.html", norm_docs=_norm_docs())

    # --- API ---
    @app.get("/api/compliance/items")
    @login_required
    def api_compliance_items():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        station_id = request.args.get("station_id")
        if not station_id:
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id requerido"}), 400
        conn = get_conn()
        # Enforce station visibility for non-admin users (ISO/seguridad: no mezclar estaciones)
        me = get_user(session.get('user_id')) or {}
        role = (me.get('role') or '').strip().lower()
        try:
            sid_req = int(station_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'bad_request', 'message': 'station_id inválido'}), 400
        if role and role != 'admin':
            sid = me.get('station_id')
            allowed = set()
            if role == 'jefe_estacion':
                # allow stations in same group
                conn0 = get_conn(); cur0 = conn0.cursor()
                cur0.execute('SELECT group_name FROM stations WHERE id=?', (sid,))
                rr = cur0.fetchone()
                gname = (rr['group_name'] if rr else None)
                if gname:
                    cur0.execute('SELECT id FROM stations WHERE brand=? AND group_name=?', ('petroleum', gname))
                    allowed = {int(r['id']) for r in cur0.fetchall()}
                else:
                    allowed = {int(sid)} if sid else set()
                conn0.close()
            else:
                allowed = {int(sid)} if sid else set()
            if sid_req not in allowed:
                return jsonify({'ok': False, 'error': 'forbidden', 'message': 'No tienes acceso a esa estación'}), 403
        cur = conn.cursor()
        cur.execute(
            """
            SELECT i.code, i.title, i.section,
                   COALESCE(r.status, 'pending') AS status,
                   COALESCE(r.status_note, '') AS status_note,
                   COALESCE(r.issue_date, '') AS issue_date,
                   COALESCE(r.expiry_date, '') AS expiry_date
            FROM compliance_items i
            LEFT JOIN compliance_records r
              ON r.item_code=i.code AND r.station_id=? AND r.brand='petroleum'
            ORDER BY i.sort_order ASC
            """,
            (station_id,),
        )
        items = []
        for r in cur.fetchall():
            row = _apply_dynamic_norm_item(dict(r))
            if row:
                items.append(row)
        items.sort(key=lambda it: (int(it.get('sort_order') or 9999), it.get('code') or it.get('item_code') or ''))
        # Compute traffic light based on expiry_date
        today = datetime.date.today()
        for it in items:
            exp = (it.get('expiry_date') or '').strip()
            traffic = 'unknown'
            days_left = None
            if exp:
                try:
                    d = datetime.date.fromisoformat(exp[:10])
                    days_left = (d - today).days
                    if days_left < 0:
                        traffic = 'expired'
                    elif days_left <= 30:
                        traffic = 'due_soon'
                    else:
                        traffic = 'ok'
                except Exception:
                    traffic = 'unknown'
            # If no files, mark as missing
            it['traffic'] = traffic
            it['days_left'] = days_left
        conn.close()
        return jsonify({"ok": True, "items": items})

    @app.get("/api/compliance/item/<code>")
    @login_required
    def api_compliance_item(code: str):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        station_id = request.args.get("station_id")
        if not station_id:
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id requerido"}), 400
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT code,title,description,section FROM compliance_items WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found", "message": "Elemento no existe"}), 404
        item = _apply_dynamic_norm_item(dict(row))
        if not item:
            conn.close()
            return jsonify({"ok": False, "error": "not_found", "message": "Elemento no disponible"}), 404
        cur.execute(
            "SELECT status, status_note, issue_date, expiry_date FROM compliance_records WHERE brand='petroleum' AND station_id=? AND item_code=?",
            (station_id, code),
        )
        rec = cur.fetchone()
        if rec:
            item["status"] = rec["status"]
            item["status_note"] = rec["status_note"] or ""
            item['issue_date'] = rec['issue_date'] or ''
            item['expiry_date'] = rec['expiry_date'] or ''
        else:
            item["status"] = "pending"
            item["status_note"] = ""
            item['issue_date'] = ''
            item['expiry_date'] = ''

        cur.execute(
            """
            SELECT version, stored_path, original_name, uploaded_at
            FROM compliance_files
            WHERE brand='petroleum' AND station_id=? AND item_code=?
            ORDER BY version DESC
            """,
            (station_id, code),
        )
        files = []
        for f in cur.fetchall():
            f = dict(f)
            f["url"] = "/uploads/" + f["stored_path"].replace("\\", "/")
            files.append(f)
        # Traffic light
        try:
            today = datetime.date.today()
            exp = (item.get('expiry_date') or '').strip()
            if exp:
                d = datetime.date.fromisoformat(exp[:10])
                item['days_left'] = (d - today).days
                if item['days_left'] < 0:
                    item['traffic'] = 'expired'
                elif item['days_left'] <= 30:
                    item['traffic'] = 'due_soon'
                else:
                    item['traffic'] = 'ok'
            else:
                item['days_left'] = None
                item['traffic'] = 'unknown'
        except Exception:
            item['days_left'] = None
            item['traffic'] = 'unknown'
        conn.close()
        return jsonify({"ok": True, "item": item, "files": files})

    @app.post("/api/compliance/item/<code>/status")
    @login_required
    @role_required("admin", "jefe_estacion")
    def api_compliance_set_status(code: str):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        station_id = data.get("station_id")
        status = data.get("status")
        note = (data.get("note") or "").strip()
        issue_date = (data.get('issue_date') or '').strip()
        expiry_date = (data.get('expiry_date') or '').strip()
        if not station_id or status not in {"pending", "in_review", "approved", "rejected"}:
            return jsonify({"ok": False, "error": "bad_request", "message": "Datos inválidos"}), 400
        try:
            sid_req = int(station_id)
        except Exception:
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id inválido"}), 400
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM compliance_items WHERE code=?", (code,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found", "message": "Elemento no existe"}), 404

        # Cross-station write guard (BUG-001 fix).
        # Espeja la lógica del GET /api/compliance/items: un jefe_estacion sólo
        # puede tocar estaciones petroleum dentro de su mismo group_name; otros
        # roles no-admin sólo su propia estación. Sin este check, cualquier
        # usuario con rol jefe_estacion podía modificar compliance_records de
        # cualquier estación petroleum.
        me = get_user(session.get('user_id')) or {}
        role = (me.get('role') or '').strip().lower()
        if role != 'admin':
            sid_owner = me.get('station_id')
            allowed: set[int] = set()
            if role == 'jefe_estacion':
                cur.execute('SELECT group_name FROM stations WHERE id=?', (sid_owner,))
                rr = cur.fetchone()
                gname = (rr['group_name'] if rr else None)
                if gname:
                    cur.execute(
                        'SELECT id FROM stations WHERE brand=? AND group_name=?',
                        ('petroleum', gname),
                    )
                    allowed = {int(r['id']) for r in cur.fetchall()}
                else:
                    allowed = {int(sid_owner)} if sid_owner else set()
            else:
                allowed = {int(sid_owner)} if sid_owner else set()
            if sid_req not in allowed:
                conn.close()
                return jsonify({
                    "ok": False, "error": "forbidden",
                    "message": "No tienes acceso a esa estación",
                }), 403

        cur.execute(
            """
            INSERT INTO compliance_records (brand, station_id, item_code, status, status_note, issue_date, expiry_date, updated_by)
            VALUES ('petroleum', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(brand, station_id, item_code) DO UPDATE SET
              status=excluded.status,
              status_note=excluded.status_note,
              issue_date=excluded.issue_date,
              expiry_date=excluded.expiry_date,
              updated_by=excluded.updated_by,
              updated_at=CURRENT_TIMESTAMP
            """,
            (station_id, code, status, note, issue_date or None, expiry_date or None, session.get('user_id')),
        )
        conn.commit()
        conn.close()
        try:
            me = ctx.get_me()
            ctx.log_action(me, "compliance_status", "compliance_record", f"{station_id}:{code}", {"status": status, "note": note, "issue_date": issue_date, "expiry_date": expiry_date})
            ctx.sign_entity(me, "compliance_record", f"{station_id}:{code}", f"status_{status}", {"note": note, "issue_date": issue_date, "expiry_date": expiry_date})
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.post("/api/compliance/item/<code>/upload")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor")
    def api_compliance_upload(code: str):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny

        station_id = request.form.get("station_id")
        f = request.files.get("file")
        if not station_id or not f or not f.filename:
            return jsonify({"ok": False, "error": "bad_request", "message": "Archivo y station_id requeridos"}), 400
        if not _is_allowed(f.filename):
            return jsonify({"ok": False, "error": "bad_request", "message": "Tipo no permitido"}), 400

        # Validate item exists
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM compliance_items WHERE code=?", (code,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "not_found", "message": "Elemento no existe"}), 404

        # Read a small chunk for magic bytes validation
        head = f.stream.read(16)
        kind = _detect_kind(head)
        if not kind:
            conn.close()
            return jsonify({"ok": False, "error": "bad_request", "message": "Archivo inválido"}), 400
        f.stream.seek(0)

        # Determine next version
        cur.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM compliance_files WHERE brand='petroleum' AND station_id=? AND item_code=?",
            (station_id, code),
        )
        next_v = int(cur.fetchone()[0] or 0) + 1

        # Store under uploads/petroleum/compliance/<station_id>/<code>/
        upload_base: Path = app.extensions["ctx"].upload_dir
        safe_name = secure_filename(f.filename)
        token = secrets.token_hex(4)
        ext = os.path.splitext(safe_name)[1].lower()
        store_dir = upload_base / "petroleum" / "compliance" / str(station_id) / code
        store_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"v{next_v}_{token}{ext}"
        stored_abs = store_dir / stored_filename
        rel_path = os.path.relpath(stored_abs, upload_base)
        get_storage().save_upload(f, rel_path)

        # Store relative path for /uploads/<path>

        cur.execute(
            """
            INSERT INTO compliance_files (brand, station_id, item_code, version, stored_path, original_name)
            VALUES ('petroleum', ?, ?, ?, ?, ?)
            """,
            (station_id, code, next_v, rel_path, safe_name),
        )
        # Move to in_review automatically on upload if pending
        cur.execute(
            """
            INSERT INTO compliance_records (brand, station_id, item_code, status, status_note, updated_by)
            VALUES ('petroleum', ?, ?, 'in_review', '', ?)
            ON CONFLICT(brand, station_id, item_code) DO UPDATE SET
              status=CASE WHEN compliance_records.status='approved' THEN 'approved' ELSE 'in_review' END,
              updated_by=excluded.updated_by,
              updated_at=CURRENT_TIMESTAMP
            """,
            (station_id, code, session.get("user_id")),
        )

        conn.commit()
        conn.close()
        try:
            me = ctx.get_me()
            ctx.log_action(me, "compliance_upload", "compliance_file", str(next_v), {"station_id": station_id, "item_code": code, "version": next_v, "original_name": safe_name})
            ctx.sign_entity(me, "compliance_file", f"{station_id}:{code}:{next_v}", "uploaded", {"station_id": station_id, "item_code": code, "version": next_v, "original_name": safe_name})
        except Exception:
            pass
        return jsonify({"ok": True, "version": next_v})


    # --- Petroleum: 3 norm documents (simple, configurable from Setup) ---
    def _norm_docs():
        return get_normative_config('petroleum')


    def _norm_docs_visible():
        return {item['code']: item for item in get_normative_items('petroleum', visible_only=True)}


    def _norm_fuel_scope(station_id: int) -> str:
        """Store one independent doc set per station using the existing schema."""
        return f"station:{int(station_id)}"

    def _apply_dynamic_norm_item(item: dict | None):
        if not item:
            return item
        docs_cfg = _norm_docs()
        code = (item.get('code') or item.get('item_code') or '').strip().lower()
        cfg = docs_cfg.get(code)
        if code in NORMATIVE_DEFAULTS and (not cfg or not cfg.get('enabled', True)):
            return None
        if cfg:
            item['title'] = cfg.get('title') or item.get('title') or ''
            item['accent_color'] = cfg.get('color') or item.get('accent_color') or ''
            item['sort_order'] = cfg.get('order') if cfg.get('order') is not None else item.get('sort_order')
            item['icon'] = cfg.get('icon') or item.get('icon') or '•'
            item['badge'] = cfg.get('badge') or item.get('badge') or ''
            item['description'] = cfg.get('description') or item.get('description') or f"Documentación y evidencias relacionadas con {item['title']}."
        return item

    def _norm_station_id_from_request():
        me = ctx.get_me()
        sid = request.args.get("station_id") or request.form.get("station_id")
        if sid is None or str(sid).strip() == "":
            if me and me.get("role") != "admin":
                return int(ctx.require_station(me))
            return None
        try:
            sid_i = int(sid)
        except Exception:
            return None
        if me and me.get("role") != "admin" and not ctx.can_access_station(me, sid_i):
            return "forbidden"
        return sid_i

    @app.get("/api/petroleum/norms/meta")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_petroleum_norms_meta():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        station_id = _norm_station_id_from_request()
        if station_id in (None, ""):
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id requerido"}), 400
        if station_id == "forbidden":
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scope = _norm_fuel_scope(int(station_id))
        conn = get_conn(); cur = conn.cursor()
        items = []
        docs_cfg = _norm_docs_visible()
        control_by_code = {}
        try:
            cur.execute(
                """
                SELECT dt.code, psc.document_status, psc.payment_status, psc.start_date, psc.renewal_date,
                       psc.notes, oc.name AS owner_name, oc.short_code AS owner_code, oc.color_hex AS owner_color
                FROM petroleum_station_control psc
                JOIN petroleum_doc_types dt ON dt.id = psc.doc_type_id
                LEFT JOIN stations s ON s.id = psc.station_id
                LEFT JOIN petroleum_owner_catalog oc ON oc.id = s.petroleum_owner_id
                WHERE psc.station_id=?
                """,
                (int(station_id),),
            )
            for crow in cur.fetchall():
                c = dict(crow)
                renewal_state = 'sin_fecha'
                days_left = None
                rd = (c.get('renewal_date') or '').strip()
                if rd:
                    try:
                        dd = datetime.date.fromisoformat(rd[:10])
                        days_left = (dd - datetime.date.today()).days
                        if days_left < 0:
                            renewal_state = 'vencido'
                        elif days_left <= 30:
                            renewal_state = 'proximo'
                        else:
                            renewal_state = 'vigente'
                    except Exception:
                        renewal_state = 'sin_fecha'
                c['renewal_state'] = renewal_state
                c['days_left'] = days_left
                control_by_code[c.get('code')] = c
        except Exception:
            control_by_code = {}
        for key, spec in docs_cfg.items():
            cur.execute(
                """
                SELECT version, stored_path, original_name, uploaded_at
                FROM petroleum_norm_files
                WHERE brand='petroleum' AND fuel_type=? AND doc_key=?
                ORDER BY version DESC
                LIMIT 1
                """,
                (scope, key),
            )
            row = cur.fetchone()
            d = {"doc_key": key, "title": spec["title"], "badge": spec.get('badge') or '', "icon": spec.get('icon') or '•', "description": spec.get('description') or '', "color": spec.get('color') or '', "has": False}
            if row:
                r = dict(row)
                r["url"] = "/uploads/" + r["stored_path"].replace("\\", "/")
                d["has"] = True
                d["file"] = r
            if key in control_by_code:
                d['control'] = control_by_code[key]
            items.append(d)
        conn.close()
        return jsonify({"ok": True, "station_id": int(station_id), "items": items})

    @app.get("/api/petroleum/norms/<doc_key>/download")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_petroleum_norms_download(doc_key: str):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        doc_key = (doc_key or "").strip().lower()
        docs_cfg = _norm_docs_visible()
        if doc_key not in docs_cfg:
            return jsonify({"ok": False, "error": "not_found"}), 404
        station_id = _norm_station_id_from_request()
        if station_id in (None, ""):
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id requerido"}), 400
        if station_id == "forbidden":
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scope = _norm_fuel_scope(int(station_id))
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            """
            SELECT stored_path
            FROM petroleum_norm_files
            WHERE brand='petroleum' AND fuel_type=? AND doc_key=?
            ORDER BY version DESC
            LIMIT 1
            """,
            (scope, doc_key),
        )
        row = cur.fetchone(); conn.close()
        if not row:
            return jsonify({"ok": False, "error": "not_found", "message": "No hay archivo vigente"}), 404
        return redirect("/uploads/" + row[0].replace("\\", "/"))

    @app.post("/api/petroleum/norms/<doc_key>/upload")
    @login_required
    @role_required("admin")
    def api_petroleum_norms_upload(doc_key: str):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        doc_key = (doc_key or "").strip().lower()
        docs_cfg = _norm_docs_visible()
        if doc_key not in docs_cfg:
            return jsonify({"ok": False, "error": "not_found"}), 404
        station_id = _norm_station_id_from_request()
        if station_id in (None, ""):
            return jsonify({"ok": False, "error": "bad_request", "message": "station_id requerido"}), 400
        if station_id == "forbidden":
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scope = _norm_fuel_scope(int(station_id))
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "bad_request", "message": "Archivo requerido"}), 400
        ext = Path(secure_filename(f.filename)).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return jsonify({"ok": False, "error": "invalid_file", "message": "Formato no permitido (PDF/JPG/PNG)"}), 400

        head = f.stream.read(16)
        if not _detect_kind(head):
            return jsonify({"ok": False, "error": "bad_request", "message": "Archivo inválido"}), 400
        f.stream.seek(0)

        upload_base: Path = app.extensions["ctx"].upload_dir
        store_dir = upload_base / "petroleum" / "normas" / str(int(station_id)) / doc_key
        store_dir.mkdir(parents=True, exist_ok=True)

        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(version),0) FROM petroleum_norm_files WHERE brand='petroleum' AND fuel_type=? AND doc_key=?",
            (scope, doc_key),
        )
        next_v = int(cur.fetchone()[0] or 0) + 1

        safe_name = secure_filename(f.filename) or f"{doc_key}{ext}"
        stored_name = f"v{next_v}_{secrets.token_hex(4)}_{safe_name}"
        stored_abs = store_dir / stored_name
        rel_path = os.path.relpath(stored_abs, upload_base)
        get_storage().save_upload(f, rel_path)

        cur.execute(
            """
            INSERT INTO petroleum_norm_files (brand, fuel_type, doc_key, title, version, stored_path, original_name, uploaded_by)
            VALUES ('petroleum', ?, ?, ?, ?, ?, ?, ?)
            """,
            (scope, doc_key, docs_cfg[doc_key]["title"], next_v, rel_path, f.filename, session.get("user_id")),
        )
        conn.commit(); conn.close()
        try:
            me = ctx.get_me()
            ctx.log_action(me, 'petroleum_norm_upload', 'petroleum_norm', doc_key, {'station_id': int(station_id), 'version': next_v, 'original_name': f.filename})
        except Exception:
            pass
        return jsonify({"ok": True, "doc_key": doc_key, "station_id": int(station_id), "version": next_v})


    # --- Petroleum admin: owner registry + renewal control ---
    def _control_doc_types(cur):
        docs_cfg = _norm_docs()
        cur.execute(
            "SELECT id, code, title, accent_color, sort_order, is_active FROM petroleum_doc_types WHERE is_active=1 ORDER BY sort_order ASC, id ASC"
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            code = (d.get('code') or '').strip().lower()
            cfg = docs_cfg.get(code)
            if code in NORMATIVE_DEFAULTS:
                if not cfg or not cfg.get('enabled', True):
                    continue
                d['title'] = cfg.get('title') or d.get('title')
                d['accent_color'] = cfg.get('color') or d.get('accent_color')
                d['sort_order'] = int(cfg.get('order') or d.get('sort_order') or 0)
                d['icon'] = cfg.get('icon') or d.get('icon') or '•'
                d['description'] = cfg.get('description') or d.get('description') or ''
            rows.append(d)
        rows.sort(key=lambda it: (int(it.get('sort_order') or 0), it.get('id') or 0))
        return rows

    def _renewal_state(renewal_date: str | None):
        rd = (renewal_date or '').strip()
        if not rd:
            return 'sin_fecha', None
        try:
            dd = datetime.date.fromisoformat(rd[:10])
            days_left = (dd - datetime.date.today()).days
            if days_left < 0:
                return 'vencido', days_left
            if days_left <= 30:
                return 'proximo', days_left
            return 'vigente', days_left
        except Exception:
            return 'sin_fecha', None

    def _entry_payload(data: dict):
        clean = {
            'station_id': int(data.get('station_id') or 0),
            'doc_type_id': int(data.get('doc_type_id') or 0),
            'start_date': (data.get('start_date') or '').strip() or None,
            'renewal_date': (data.get('renewal_date') or '').strip() or None,
            'document_status': (data.get('document_status') or 'vigente').strip().lower(),
            'payment_status': (data.get('payment_status') or 'pendiente').strip().lower(),
            'last_payment_date': (data.get('last_payment_date') or '').strip() or None,
            'amount_due': data.get('amount_due'),
            'notes': (data.get('notes') or '').strip(),
        }
        if clean['document_status'] not in {'vigente','debe_documento','en_revision','vencido','no_aplica'}:
            clean['document_status'] = 'vigente'
        if clean['payment_status'] not in {'pagado','pendiente','vencido','no_aplica'}:
            clean['payment_status'] = 'pendiente'
        try:
            clean['amount_due'] = float(clean['amount_due']) if clean['amount_due'] not in (None, '', 'null') else None
        except Exception:
            clean['amount_due'] = None
        if clean['station_id'] <= 0 or clean['doc_type_id'] <= 0:
            return None
        return clean

    def _control_entry_rows(cur, owner_id=None, station_id=None, doc_type_id=None, renewal_state_filter=None, payment_status=None):
        sql = (
            "SELECT psc.id, psc.station_id, psc.doc_type_id, psc.start_date, psc.renewal_date, psc.document_status, "
            "psc.payment_status, psc.last_payment_date, psc.amount_due, psc.notes, psc.updated_at, psc.created_at, "
            "s.name AS station_name, s.station_number, s.code AS station_code, s.petroleum_owner_id, "
            "oc.name AS owner_name, oc.short_code AS owner_code, oc.color_hex AS owner_color, "
            "dt.code AS doc_code, dt.title AS doc_title, dt.accent_color AS doc_color "
            "FROM petroleum_station_control psc "
            "JOIN stations s ON s.id = psc.station_id AND s.brand='petroleum' "
            "JOIN petroleum_doc_types dt ON dt.id = psc.doc_type_id "
            "LEFT JOIN petroleum_owner_catalog oc ON oc.id = s.petroleum_owner_id "
            "WHERE 1=1"
        )
        params = []
        if owner_id:
            sql += " AND s.petroleum_owner_id=?"
            params.append(int(owner_id))
        if station_id:
            sql += " AND psc.station_id=?"
            params.append(int(station_id))
        if doc_type_id:
            sql += " AND psc.doc_type_id=?"
            params.append(int(doc_type_id))
        if payment_status in {'pagado','pendiente','vencido','no_aplica'}:
            sql += " AND psc.payment_status=?"
            params.append(payment_status)
        sql += " ORDER BY COALESCE(s.station_number, s.id), dt.sort_order, dt.id"
        cur.execute(sql, tuple(params))
        docs_cfg = _norm_docs()
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            code = (d.get('doc_code') or '').strip().lower()
            cfg = docs_cfg.get(code)
            if code in NORMATIVE_DEFAULTS and cfg and not cfg.get('enabled', True):
                continue
            if cfg:
                d['doc_title'] = cfg.get('title') or d.get('doc_title')
                d['doc_color'] = cfg.get('color') or d.get('doc_color')
                d['doc_sort_order'] = int(cfg.get('order') or d.get('sort_order') or 0)
                d['doc_icon'] = cfg.get('icon') or d.get('doc_icon') or '•'
                d['doc_description'] = cfg.get('description') or d.get('doc_description') or ''
            else:
                d['doc_sort_order'] = int(d.get('sort_order') or 0)
                d['doc_icon'] = d.get('doc_icon') or '•'
                d['doc_description'] = d.get('doc_description') or ''
            renewal_state, days_left = _renewal_state(d.get('renewal_date'))
            d['renewal_state'] = renewal_state
            d['days_left'] = days_left
            d['has_owner'] = bool(d.get('petroleum_owner_id'))
            d['attention_flags'] = {
                'document': d.get('document_status') in {'debe_documento', 'vencido'},
                'payment': d.get('payment_status') in {'pendiente', 'vencido'},
                'renewal': renewal_state in {'proximo', 'vencido'},
            }
            if renewal_state_filter in {'vigente','proximo','vencido','sin_fecha'} and d['renewal_state'] != renewal_state_filter:
                continue
            rows.append(d)
        rows.sort(key=lambda row: (str(row.get('station_number') or row.get('station_id') or ''), int(row.get('doc_sort_order') or 0), int(row.get('id') or 0)))
        return rows

    @app.get('/api/petroleum/control/meta')
    @login_required
    @role_required('admin')
    def api_petroleum_control_meta():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name, short_code, color_hex, phone, email, notes, is_active FROM petroleum_owner_catalog WHERE is_active=1 ORDER BY name ASC")
        owners = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id, name, code, station_number, group_name, petroleum_owner_id FROM stations WHERE brand='petroleum' ORDER BY COALESCE(station_number, id) ASC, id ASC")
        stations = [dict(r) for r in cur.fetchall()]
        doc_types = _control_doc_types(cur)
        rows = _control_entry_rows(cur)
        summary = {
            'total': len(rows),
            'vigentes': sum(1 for r in rows if r.get('renewal_state') == 'vigente' and r.get('document_status') == 'vigente'),
            'por_vencer': sum(1 for r in rows if r.get('renewal_state') == 'proximo'),
            'vencidos': sum(1 for r in rows if r.get('renewal_state') == 'vencido' or r.get('document_status') == 'vencido'),
            'pagos_pendientes': sum(1 for r in rows if r.get('payment_status') in {'pendiente', 'vencido'}),
            'documentos_pendientes': sum(1 for r in rows if r.get('document_status') in {'debe_documento', 'vencido'}),
        }
        conn.close()
        return jsonify({'ok': True, 'owners': owners, 'stations': stations, 'doc_types': doc_types, 'summary': summary})

    @app.get('/api/petroleum/control/entries')
    @login_required
    @role_required('admin')
    def api_petroleum_control_entries():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        owner_id = (request.args.get('owner_id') or '').strip()
        station_id = (request.args.get('station_id') or '').strip()
        doc_type_id = (request.args.get('doc_type_id') or '').strip()
        renewal_state_filter = (request.args.get('renewal_state') or '').strip().lower()
        payment_status = (request.args.get('payment_status') or '').strip().lower()
        conn = get_conn(); cur = conn.cursor()
        rows = _control_entry_rows(
            cur,
            owner_id=int(owner_id) if owner_id.isdigit() else None,
            station_id=int(station_id) if station_id.isdigit() else None,
            doc_type_id=int(doc_type_id) if doc_type_id.isdigit() else None,
            renewal_state_filter=renewal_state_filter if renewal_state_filter in {'vigente','proximo','vencido','sin_fecha'} else None,
            payment_status=payment_status if payment_status in {'pagado','pendiente','vencido','no_aplica'} else None,
        )
        conn.close()
        return jsonify({'ok': True, 'items': rows})

    @app.post('/api/petroleum/control/owners')
    @login_required
    @role_required('admin')
    def api_petroleum_control_owner_create():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        short_code = (data.get('short_code') or '').strip().upper()
        color_hex = (data.get('color_hex') or '#D4AF37').strip()
        if not name or not short_code:
            return jsonify({'ok': False, 'error': 'bad_request', 'message': 'Nombre y clave requeridos'}), 400
        conn = get_conn(); cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO petroleum_owner_catalog (name, short_code, color_hex, phone, email, notes, is_active) VALUES (?,?,?,?,?,?,1)",
                (name, short_code[:8], color_hex[:20], (data.get('phone') or '').strip(), (data.get('email') or '').strip(), (data.get('notes') or '').strip()),
            )
            owner_id = cur.lastrowid
            conn.commit()
        except Exception:
            conn.close()
            return jsonify({'ok': False, 'error': 'duplicate', 'message': 'La clave del responsable ya existe'}), 400
        conn.close()
        ctx.log_action(ctx.get_me(), 'petroleum_owner_create', 'petroleum_owner_catalog', str(owner_id), {'name': name, 'short_code': short_code[:8]})
        return jsonify({'ok': True, 'id': owner_id})

    @app.patch('/api/petroleum/control/owners/<int:owner_id>')
    @login_required
    @role_required('admin')
    def api_petroleum_control_owner_update(owner_id: int):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        fields = []
        vals = []
        for key in ('name','short_code','color_hex','phone','email','notes','is_active'):
            if key in data:
                fields.append(f"{key}=?")
                val = data.get(key)
                if key == 'short_code' and val is not None:
                    val = str(val).strip().upper()[:8]
                vals.append(val)
        if not fields:
            return jsonify({'ok': False, 'error': 'no_changes'}), 400
        vals.append(owner_id)
        conn = get_conn(); cur = conn.cursor()
        try:
            cur.execute(f"UPDATE petroleum_owner_catalog SET {', '.join(fields)} WHERE id=?", tuple(vals))
            conn.commit(); conn.close()
        except Exception:
            conn.close()
            return jsonify({'ok': False, 'error': 'duplicate', 'message': 'No se pudo actualizar el responsable'}), 400
        ctx.log_action(ctx.get_me(), 'petroleum_owner_update', 'petroleum_owner_catalog', str(owner_id), {'fields': fields})
        return jsonify({'ok': True})

    @app.post('/api/petroleum/control/stations/<int:station_id>/owner')
    @login_required
    @role_required('admin')
    def api_petroleum_control_assign_owner(station_id: int):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        owner_id = data.get('owner_id')
        try:
            owner_id = int(owner_id) if owner_id not in (None, '', 'null') else None
        except Exception:
            owner_id = None
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE stations SET petroleum_owner_id=? WHERE id=? AND brand='petroleum'", (owner_id, station_id))
        conn.commit(); conn.close()
        ctx.log_action(ctx.get_me(), 'petroleum_station_owner', 'stations', str(station_id), {'owner_id': owner_id})
        return jsonify({'ok': True})

    @app.post('/api/petroleum/control/doc-types')
    @login_required
    @role_required('admin')
    def api_petroleum_control_doc_type_create():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        code = (data.get('code') or '').strip().lower().replace(' ', '_')
        title = (data.get('title') or '').strip()
        if not code or not title:
            return jsonify({'ok': False, 'error': 'bad_request', 'message': 'Código y título requeridos'}), 400
        color = (data.get('accent_color') or '#D4AF37').strip()
        sort_order = int(data.get('sort_order') or 100)
        conn = get_conn(); cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO petroleum_doc_types (code, title, accent_color, sort_order, is_active) VALUES (?,?,?,?,1)",
                (code[:40], title[:120], color[:20], sort_order),
            )
            doc_type_id = cur.lastrowid
            conn.commit(); conn.close()
        except Exception:
            conn.close()
            return jsonify({'ok': False, 'error': 'duplicate', 'message': 'Ese documento ya existe'}), 400
        ctx.log_action(ctx.get_me(), 'petroleum_doc_type_create', 'petroleum_doc_types', str(doc_type_id), {'code': code[:40], 'title': title[:120]})
        return jsonify({'ok': True, 'id': doc_type_id})

    @app.post('/api/petroleum/control/entries')
    @login_required
    @role_required('admin')
    def api_petroleum_control_entry_create():
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        clean = _entry_payload(data)
        if not clean:
            return jsonify({'ok': False, 'error': 'bad_request', 'message': 'Estación y documento son requeridos'}), 400
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM stations WHERE id=? AND brand='petroleum'", (clean['station_id'],))
        if not cur.fetchone():
            conn.close(); return jsonify({'ok': False, 'error': 'not_found', 'message': 'Estación no encontrada'}), 404
        cur.execute("SELECT id FROM petroleum_doc_types WHERE id=?", (clean['doc_type_id'],))
        if not cur.fetchone():
            conn.close(); return jsonify({'ok': False, 'error': 'not_found', 'message': 'Documento no encontrado'}), 404
        uid = session.get('user_id')
        cur.execute(
            """
            INSERT INTO petroleum_station_control (station_id, doc_type_id, start_date, renewal_date, document_status, payment_status, last_payment_date, amount_due, notes, created_by, updated_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(station_id, doc_type_id) DO UPDATE SET
                start_date=excluded.start_date,
                renewal_date=excluded.renewal_date,
                document_status=excluded.document_status,
                payment_status=excluded.payment_status,
                last_payment_date=excluded.last_payment_date,
                amount_due=excluded.amount_due,
                notes=excluded.notes,
                updated_by=excluded.updated_by,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                clean['station_id'], clean['doc_type_id'], clean['start_date'], clean['renewal_date'], clean['document_status'],
                clean['payment_status'], clean['last_payment_date'], clean['amount_due'], clean['notes'], uid, uid,
            ),
        )
        conn.commit()
        cur.execute("SELECT id FROM petroleum_station_control WHERE station_id=? AND doc_type_id=?", (clean['station_id'], clean['doc_type_id']))
        entry_id = int(cur.fetchone()[0])
        conn.close()
        ctx.log_action(ctx.get_me(), 'petroleum_control_upsert', 'petroleum_station_control', str(entry_id), clean)
        return jsonify({'ok': True, 'id': entry_id})

    @app.patch('/api/petroleum/control/entries/<int:entry_id>')
    @login_required
    @role_required('admin')
    def api_petroleum_control_entry_update(entry_id: int):
        deny = _ensure_brand_petroleum()
        if deny:
            return deny
        data = request.get_json(silent=True) or {}
        allowed = {
            'start_date', 'renewal_date', 'document_status', 'payment_status', 'last_payment_date', 'amount_due', 'notes'
        }
        clean = {k: data.get(k) for k in data.keys() if k in allowed}
        if not clean:
            return jsonify({'ok': False, 'error': 'no_changes'}), 400
        parts = []
        vals = []
        for key, val in clean.items():
            if key in {'document_status'}:
                vv = str(val or '').strip().lower()
                if vv not in {'vigente','debe_documento','en_revision','vencido','no_aplica'}:
                    continue
                val = vv
            elif key in {'payment_status'}:
                vv = str(val or '').strip().lower()
                if vv not in {'pagado','pendiente','vencido','no_aplica'}:
                    continue
                val = vv
            elif key == 'amount_due':
                try:
                    val = float(val) if val not in (None, '', 'null') else None
                except Exception:
                    val = None
            elif key in {'start_date','renewal_date','last_payment_date'}:
                val = (str(val or '').strip() or None)
            else:
                val = str(val or '').strip()
            parts.append(f"{key}=?")
            vals.append(val)
        parts.append('updated_by=?')
        vals.append(session.get('user_id'))
        parts.append('updated_at=CURRENT_TIMESTAMP')
        vals.append(entry_id)
        conn = get_conn(); cur = conn.cursor()
        cur.execute(f"UPDATE petroleum_station_control SET {', '.join(parts)} WHERE id=?", tuple(vals))
        conn.commit(); conn.close()
        ctx.log_action(ctx.get_me(), 'petroleum_control_update', 'petroleum_station_control', str(entry_id), {'fields': list(clean.keys())})
        return jsonify({'ok': True})

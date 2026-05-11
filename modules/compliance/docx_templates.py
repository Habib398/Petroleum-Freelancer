"""Admin API for the DOCX template engine.

This module exposes the HTTP surface for the new ``<<VARIABLE>>`` based
template system built on :mod:`services.docx_engine`. It coexists with the
legacy PDF-coordinate engine in :mod:`modules.compliance.documental_docs`
without conflict: the two systems use disjoint table names (``docx_*`` vs
``doc_*``) and disjoint URL prefixes (``/admin/docx/*`` vs
``/admin/<module>/docs/*``).

All routes are **admin-only**. There is no staff UI in this iteration —
admins generate documents on behalf of stations, and the eventual staff
view-only access will be wired through the expediente integration.

Endpoints
---------

Templates
~~~~~~~~~
- ``GET    /admin/docx/templates``                      List templates.
- ``POST   /admin/docx/templates``                      Create a template + upload v1.0.
- ``GET    /admin/docx/templates/<id>``                 Detail (template + versions + current fields).
- ``POST   /admin/docx/templates/<id>/versions``        Upload a new version (auto-bumps label).
- ``POST   /admin/docx/templates/<id>/publish``         Toggle ``is_published``.
- ``GET    /admin/docx/templates/<id>/fields``          Field config of the current version.
- ``POST   /admin/docx/templates/<id>/fields``          Save field config.

Generated documents
~~~~~~~~~~~~~~~~~~~
- ``POST   /admin/docx/generate``                       Generate a filled document.
- ``GET    /admin/docx/generated``                      List generated docs (filterable).
- ``GET    /admin/docx/generated/<id>``                 Detail.
- ``GET    /admin/docx/generated/<id>/download``        Download the .docx (or .pdf if available).
- ``POST   /admin/docx/generated/<id>/approve``         Mark approved.
- ``POST   /admin/docx/generated/<id>/cancel``          Mark cancelled with reason.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

from db import get_conn
from services.brand import get_brand
from services.docx_engine import parse_template, render_docx
from services.docx_pdf import convert_to_pdf, is_available as pdf_available
from services.docx_variables import (
    canonical,
    classify,
    auto_source_for,
    label_for,
    merge_with_manual,
    resolve_auto_values,
)


# ---------------------------------------------------------------------------
# Helpers (module-level so they can be unit-tested without an app context)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bump_version(prev_label: str | None) -> str:
    """Return the next version label given the previous one.

    Strategy: if previous looks like ``vMAJOR.MINOR``, bump MINOR. Otherwise
    fall back to ``v1.0``. Admin can override via the API later (out of scope
    for v1).
    """
    if not prev_label:
        return "v1.0"
    m = re.match(r"^v(\d+)\.(\d+)$", prev_label.strip())
    if not m:
        return "v1.0"
    major, minor = int(m.group(1)), int(m.group(2))
    return f"v{major}.{minor + 1}"


def _safe_code(raw: str) -> str:
    """Sanitize a template code (file-system-safe slug)."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:60]


def _validate_module(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "general"
    return s[:40]


def _row(cursor, sql: str, params: tuple = ()) -> dict | None:
    row = cursor.execute(sql, params).fetchone()
    return dict(row) if row else None


def _rows(cursor, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in cursor.execute(sql, params).fetchall()]


# Allowed transitions for generated-document status. Keeping this explicit
# avoids accidental skips (e.g. cancelled -> approved).
_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "borrador":       {"en_revision", "aprobado", "cancelado"},
    "en_revision":    {"aprobado", "cancelado"},
    "aprobado":       {"cancelado", "reemplazado"},
    "cancelado":      set(),
    "enviado_correo": {"reemplazado"},
    "reemplazado":    set(),
}


def _can_transition(current: str, target: str) -> bool:
    return target in _STATUS_TRANSITIONS.get((current or "").lower(), set())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app):
    ctx = app.extensions["ctx"]
    storage = app.extensions["storage"]
    upload_dir = Path(ctx.upload_dir)
    login_required = ctx.login_required

    # ---------- Auth gate ----------

    def _admin_or_403() -> dict:
        me = ctx.get_me()
        if not me:
            abort(401)
        if (me.get("role") or "").lower() != "admin":
            abort(403)
        return me

    # ---------- File storage helpers ----------

    def _template_relpath(brand: str, module: str, code: str, version_label: str, original_name: str) -> str:
        suffix = Path(secure_filename(original_name) or "template.docx").suffix.lower() or ".docx"
        if suffix != ".docx":
            suffix = ".docx"
        return f"docx_templates/{brand}/{module}/{code}/{version_label}{suffix}"

    def _generated_relpath(brand: str, station_id: int | None, template_code: str, generated_id: int) -> str:
        sid = station_id if station_id else 0
        return f"docx_generated/{brand}/station_{sid}/{template_code}/doc_{generated_id}.docx"

    # ---------- Field persistence ----------

    def _persist_fields(conn, template_id: int, version_id: int, detected: list[dict],
                        carry_from_version_id: int | None = None) -> None:
        """Insert ``docx_template_fields`` rows for a freshly parsed version.

        If ``carry_from_version_id`` is given, the field-config for
        same-named variables in that previous version is carried over so
        admins don't lose customization when re-uploading.
        """
        cur = conn.cursor()
        carried: dict[str, dict] = {}
        if carry_from_version_id:
            for r in cur.execute(
                "SELECT variable_name, label, field_kind, auto_source, fixed_value, "
                "placeholder, sort_order, is_required, field_type "
                "FROM docx_template_fields WHERE version_id=?",
                (int(carry_from_version_id),),
            ).fetchall():
                carried[(r["variable_name"] or "").upper()] = dict(r)

        for idx, item in enumerate(detected):
            var = canonical(item["variable"])
            previous = carried.get(var)
            if previous:
                cur.execute(
                    "INSERT INTO docx_template_fields (template_id, version_id, variable_name, label, "
                    "field_kind, auto_source, fixed_value, placeholder, sort_order, is_required, field_type) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        int(template_id), int(version_id), var,
                        previous.get("label") or item.get("label") or label_for(var),
                        previous.get("field_kind") or item.get("kind") or "manual",
                        previous.get("auto_source") if previous.get("field_kind") == "auto"
                            else (item.get("auto_source") or auto_source_for(var)),
                        previous.get("fixed_value"),
                        previous.get("placeholder"),
                        int(previous.get("sort_order") or idx),
                        int(previous.get("is_required") or 0),
                        previous.get("field_type") or "text",
                    ),
                )
            else:
                cur.execute(
                    "INSERT INTO docx_template_fields (template_id, version_id, variable_name, label, "
                    "field_kind, auto_source, fixed_value, placeholder, sort_order, is_required, field_type) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        int(template_id), int(version_id), var,
                        item.get("label") or label_for(var),
                        item.get("kind") or "manual",
                        item.get("auto_source") or auto_source_for(var),
                        None, None, idx, 0, "text",
                    ),
                )

    def _save_uploaded_template(file_storage, brand: str, module: str, code: str, version_label: str) -> tuple[str, int]:
        """Persist the uploaded ``.docx`` and return ``(relpath, size_bytes)``."""
        if not file_storage or not (file_storage.filename or "").lower().endswith(".docx"):
            abort(400, description="docx_required")
        relpath = _template_relpath(brand, module, code, version_label, file_storage.filename)
        storage.save_upload(
            file_storage, relpath,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        local = storage.ensure_local(relpath)
        size = local.stat().st_size if local.exists() else 0
        return relpath, size

    # ---------- Template routes ----------

    @app.get("/admin/docx/templates")
    @login_required
    def docx_list_templates():
        _admin_or_403()
        brand = get_brand()
        module_filter = (request.args.get("module") or "").strip().lower() or None
        only_published = request.args.get("published") == "1"

        conn = get_conn(); cur = conn.cursor()
        sql = (
            "SELECT t.*, v.version_label AS current_version_label, v.uploaded_at AS current_version_at, "
            "       (SELECT COUNT(*) FROM docx_template_fields f WHERE f.version_id=t.current_version_id) AS field_count "
            "FROM docx_templates t "
            "LEFT JOIN docx_template_versions v ON v.id=t.current_version_id "
            "WHERE t.brand=? AND t.is_active=1"
        )
        params: list = [brand]
        if module_filter:
            sql += " AND t.module=?"
            params.append(module_filter)
        if only_published:
            sql += " AND t.is_published=1"
        sql += " ORDER BY t.updated_at DESC, t.id DESC"
        items = _rows(cur, sql, tuple(params))
        conn.close()
        return jsonify({"ok": True, "templates": items, "pdf_available": pdf_available()})

    @app.post("/admin/docx/templates")
    @login_required
    def docx_create_template():
        me = _admin_or_403()
        brand = get_brand()
        f = request.files.get("file")
        code = _safe_code(request.form.get("code") or "")
        name = (request.form.get("name") or "").strip()
        module = _validate_module(request.form.get("module") or "")
        description = (request.form.get("description") or "").strip() or None

        if not f or not (f.filename or "").lower().endswith(".docx"):
            return jsonify({"ok": False, "error": "docx_required",
                            "message": "Adjunta un archivo .docx en el campo 'file'."}), 400
        if not code or not name:
            return jsonify({"ok": False, "error": "missing_fields",
                            "message": "Faltan 'code' y/o 'name'."}), 400

        conn = get_conn(); cur = conn.cursor()

        # Reject duplicate (brand, module, code).
        existing = cur.execute(
            "SELECT id FROM docx_templates WHERE brand=? AND module=? AND code=?",
            (brand, module, code),
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"ok": False, "error": "code_already_exists",
                            "message": f"Ya existe una plantilla con code='{code}' en el módulo '{module}'."}), 409

        # Save the file under v1.0 BEFORE inserting (so we have the relpath).
        version_label = "v1.0"
        relpath, size = _save_uploaded_template(f, brand, module, code, version_label)

        try:
            local_path = storage.ensure_local(relpath)
            detected = parse_template(local_path)
        except Exception as e:
            # Clean up the orphan file so admin can retry without ghost storage.
            try:
                storage.delete(relpath)
            except Exception:
                pass
            conn.close()
            return jsonify({"ok": False, "error": "parse_failed",
                            "message": f"No se pudo leer el .docx: {e}"}), 400

        cur.execute(
            "INSERT INTO docx_templates (brand, module, code, name, description, is_published, is_active, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,0,1,?,?,?)",
            (brand, module, code, name, description, int(me["id"]), _now_iso(), _now_iso()),
        )
        template_id = int(cur.lastrowid)

        cur.execute(
            "INSERT INTO docx_template_versions (template_id, version_label, file_path, original_filename, file_size_bytes, is_current, uploaded_by) "
            "VALUES (?,?,?,?,?,1,?)",
            (template_id, version_label, relpath, secure_filename(f.filename or ""), size, int(me["id"])),
        )
        version_id = int(cur.lastrowid)
        cur.execute("UPDATE docx_templates SET current_version_id=? WHERE id=?", (version_id, template_id))

        _persist_fields(conn, template_id, version_id, detected)
        conn.commit()

        # Audit
        try:
            ctx.log_action(me, "docx_template_create", "docx_templates", str(template_id),
                           {"module": module, "code": code, "version": version_label, "fields": len(detected)})
        except Exception:
            pass

        fields = _rows(cur, "SELECT * FROM docx_template_fields WHERE version_id=? ORDER BY sort_order, id", (version_id,))
        conn.close()
        return jsonify({
            "ok": True, "template_id": template_id, "version_id": version_id,
            "version_label": version_label, "fields": fields,
        })

    @app.get("/admin/docx/templates/<int:template_id>")
    @login_required
    def docx_template_detail(template_id: int):
        _admin_or_403()
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT * FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl:
            conn.close(); abort(404)
        versions = _rows(cur, "SELECT * FROM docx_template_versions WHERE template_id=? ORDER BY uploaded_at DESC, id DESC", (template_id,))
        fields: list[dict] = []
        if tpl.get("current_version_id"):
            fields = _rows(cur,
                "SELECT * FROM docx_template_fields WHERE version_id=? ORDER BY sort_order, id",
                (int(tpl["current_version_id"]),),
            )
        conn.close()
        return jsonify({"ok": True, "template": tpl, "versions": versions, "fields": fields})

    @app.post("/admin/docx/templates/<int:template_id>/versions")
    @login_required
    def docx_upload_new_version(template_id: int):
        me = _admin_or_403()
        brand = get_brand()
        f = request.files.get("file")
        notes = (request.form.get("notes") or "").strip() or None
        if not f or not (f.filename or "").lower().endswith(".docx"):
            return jsonify({"ok": False, "error": "docx_required"}), 400

        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT * FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl:
            conn.close(); abort(404)

        prev = _row(cur,
            "SELECT * FROM docx_template_versions WHERE template_id=? ORDER BY uploaded_at DESC, id DESC LIMIT 1",
            (template_id,),
        )
        new_label = _bump_version(prev["version_label"] if prev else None)

        relpath, size = _save_uploaded_template(f, brand, tpl["module"], tpl["code"], new_label)
        try:
            detected = parse_template(storage.ensure_local(relpath))
        except Exception as e:
            try:
                storage.delete(relpath)
            except Exception:
                pass
            conn.close()
            return jsonify({"ok": False, "error": "parse_failed", "message": str(e)}), 400

        cur.execute("UPDATE docx_template_versions SET is_current=0 WHERE template_id=?", (template_id,))
        cur.execute(
            "INSERT INTO docx_template_versions (template_id, version_label, file_path, original_filename, file_size_bytes, notes, is_current, uploaded_by) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (template_id, new_label, relpath, secure_filename(f.filename or ""), size, notes, int(me["id"])),
        )
        new_version_id = int(cur.lastrowid)
        cur.execute(
            "UPDATE docx_templates SET current_version_id=?, updated_at=? WHERE id=?",
            (new_version_id, _now_iso(), template_id),
        )

        _persist_fields(conn, template_id, new_version_id, detected,
                        carry_from_version_id=int(prev["id"]) if prev else None)
        conn.commit()

        try:
            ctx.log_action(me, "docx_template_new_version", "docx_templates", str(template_id),
                           {"version": new_label, "fields": len(detected), "notes": notes})
        except Exception:
            pass

        fields = _rows(cur, "SELECT * FROM docx_template_fields WHERE version_id=? ORDER BY sort_order, id", (new_version_id,))
        conn.close()
        return jsonify({"ok": True, "version_id": new_version_id, "version_label": new_label, "fields": fields})

    @app.post("/admin/docx/templates/<int:template_id>/publish")
    @login_required
    def docx_template_publish(template_id: int):
        me = _admin_or_403()
        brand = get_brand()
        body = request.get_json(silent=True) or {}
        target = bool(body.get("is_published", True))
        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT id FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl:
            conn.close(); abort(404)
        cur.execute(
            "UPDATE docx_templates SET is_published=?, updated_at=? WHERE id=?",
            (1 if target else 0, _now_iso(), template_id),
        )
        conn.commit(); conn.close()
        try:
            ctx.log_action(me, "docx_template_publish", "docx_templates", str(template_id),
                           {"is_published": target})
        except Exception:
            pass
        return jsonify({"ok": True, "is_published": target})

    @app.get("/admin/docx/templates/<int:template_id>/fields")
    @login_required
    def docx_template_fields_get(template_id: int):
        _admin_or_403()
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT * FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl or not tpl.get("current_version_id"):
            conn.close()
            return jsonify({"ok": True, "fields": []})
        fields = _rows(cur,
            "SELECT * FROM docx_template_fields WHERE version_id=? ORDER BY sort_order, id",
            (int(tpl["current_version_id"]),),
        )
        conn.close()
        return jsonify({"ok": True, "fields": fields, "version_id": tpl["current_version_id"]})

    @app.post("/admin/docx/templates/<int:template_id>/fields")
    @login_required
    def docx_template_fields_save(template_id: int):
        me = _admin_or_403()
        brand = get_brand()
        body = request.get_json(silent=True) or {}
        incoming = body.get("fields") or []
        if not isinstance(incoming, list):
            return jsonify({"ok": False, "error": "bad_payload",
                            "message": "Expected 'fields' to be a list."}), 400

        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT * FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl:
            conn.close(); abort(404)
        version_id = int(tpl.get("current_version_id") or 0)
        if not version_id:
            conn.close()
            return jsonify({"ok": False, "error": "no_current_version"}), 400

        allowed_kinds = {"auto", "manual", "fixed", "image", "signature", "date_today"}
        allowed_types = {"text", "textarea", "date", "number"}
        updated = 0
        for item in incoming:
            if not isinstance(item, dict) or "id" not in item:
                continue
            field_id = int(item["id"])
            kind = (item.get("field_kind") or "manual").lower()
            if kind not in allowed_kinds:
                kind = "manual"
            ftype = (item.get("field_type") or "text").lower()
            if ftype not in allowed_types:
                ftype = "text"
            cur.execute(
                "UPDATE docx_template_fields SET label=?, field_kind=?, auto_source=?, fixed_value=?, "
                "placeholder=?, sort_order=?, is_required=?, field_type=? "
                "WHERE id=? AND template_id=? AND version_id=?",
                (
                    (item.get("label") or "").strip() or None,
                    kind,
                    (item.get("auto_source") or "").strip() or None,
                    (item.get("fixed_value") or None),
                    (item.get("placeholder") or "").strip() or None,
                    int(item.get("sort_order") or 0),
                    1 if item.get("is_required") else 0,
                    ftype,
                    field_id, template_id, version_id,
                ),
            )
            updated += cur.rowcount
        conn.commit()

        try:
            ctx.log_action(me, "docx_template_fields_save", "docx_templates", str(template_id),
                           {"version_id": version_id, "updated": updated})
        except Exception:
            pass

        fields = _rows(cur, "SELECT * FROM docx_template_fields WHERE version_id=? ORDER BY sort_order, id", (version_id,))
        conn.close()
        return jsonify({"ok": True, "updated": updated, "fields": fields})

    # ---------- Generation routes ----------

    @app.post("/admin/docx/generate")
    @login_required
    def docx_generate():
        me = _admin_or_403()
        brand = get_brand()
        body = request.get_json(silent=True) or {}
        try:
            template_id = int(body.get("template_id") or 0)
        except (TypeError, ValueError):
            template_id = 0
        try:
            station_id = int(body.get("station_id")) if body.get("station_id") else None
        except (TypeError, ValueError):
            station_id = None
        manual_values = body.get("manual_values") or {}
        title_override = (body.get("title") or "").strip() or None

        if not template_id:
            return jsonify({"ok": False, "error": "template_id_required"}), 400
        if not isinstance(manual_values, dict):
            return jsonify({"ok": False, "error": "manual_values_must_be_object"}), 400

        conn = get_conn(); cur = conn.cursor()
        tpl = _row(cur, "SELECT * FROM docx_templates WHERE id=? AND brand=?", (template_id, brand))
        if not tpl:
            conn.close(); abort(404, description="template_not_found")
        version_id = int(tpl.get("current_version_id") or 0)
        version = _row(cur, "SELECT * FROM docx_template_versions WHERE id=?", (version_id,)) if version_id else None
        if not version:
            conn.close()
            return jsonify({"ok": False, "error": "template_has_no_version"}), 400

        # Compose the values dict: auto-resolved + manual override + fixed values
        # set in field config + system-resolved date_today.
        fields = _rows(cur, "SELECT * FROM docx_template_fields WHERE version_id=?", (version_id,))
        auto_values = resolve_auto_values(station_id, conn=conn) if station_id else {}

        values: dict[str, Any] = {}
        image_values: dict[str, str] = {}
        for f in fields:
            var = canonical(f["variable_name"])
            kind = (f.get("field_kind") or "manual").lower()
            if kind == "auto":
                values[var] = auto_values.get(var)
            elif kind == "fixed":
                values[var] = f.get("fixed_value")
            elif kind == "date_today":
                values[var] = auto_values.get(var) or datetime.now().date().isoformat()
            elif kind == "image":
                # Image source comes from the auto_values resolution (logo paths).
                src = auto_values.get(var)
                if src:
                    image_values[var] = str(storage.ensure_local(src))
        # Manual values override anything else (admin can deliberately overwrite an auto value).
        values = merge_with_manual(values, manual_values)

        # Insert the row first to get an ID for the output filename.
        cur.execute(
            "INSERT INTO docx_generated_documents (brand, template_id, version_id, station_id, title, "
            "field_values_json, status, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                brand, template_id, version_id, station_id,
                title_override or tpl.get("name"),
                json.dumps(values, ensure_ascii=False, default=str),
                "borrador", int(me["id"]), _now_iso(),
            ),
        )
        generated_id = int(cur.lastrowid)

        out_rel = _generated_relpath(brand, station_id, tpl["code"], generated_id)
        out_local = upload_dir / out_rel
        out_local.parent.mkdir(parents=True, exist_ok=True)

        try:
            template_local = storage.ensure_local(version["file_path"])
            render_docx(template_local, out_local, values=values, image_values=image_values)
            storage.upload_local_file(
                out_local, out_rel,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            cur.execute("DELETE FROM docx_generated_documents WHERE id=?", (generated_id,))
            conn.commit(); conn.close()
            return jsonify({"ok": False, "error": "render_failed", "message": str(e)}), 500

        # Optional PDF (no-op until a backend is wired).
        pdf_rel = None
        if pdf_available():
            try:
                pdf_local = out_local.with_suffix(".pdf")
                if convert_to_pdf(out_local, pdf_local):
                    pdf_rel = out_rel.rsplit(".docx", 1)[0] + ".pdf"
                    storage.upload_local_file(pdf_local, pdf_rel, content_type="application/pdf")
            except Exception:
                pdf_rel = None  # PDF is best-effort; never fail the docx generation.

        cur.execute(
            "UPDATE docx_generated_documents SET docx_path=?, pdf_path=? WHERE id=?",
            (out_rel, pdf_rel, generated_id),
        )
        conn.commit()

        try:
            ctx.log_action(me, "docx_generate", "docx_generated_documents", str(generated_id),
                           {"template_id": template_id, "station_id": station_id, "version_id": version_id})
        except Exception:
            pass

        result = _row(cur, "SELECT * FROM docx_generated_documents WHERE id=?", (generated_id,))
        conn.close()
        return jsonify({"ok": True, "generated": result})

    @app.get("/admin/docx/generated")
    @login_required
    def docx_list_generated():
        _admin_or_403()
        brand = get_brand()
        sql = (
            "SELECT g.*, t.name AS template_name, t.code AS template_code, t.module AS template_module, "
            "       s.name AS station_name, s.code AS station_code "
            "FROM docx_generated_documents g "
            "LEFT JOIN docx_templates t ON t.id=g.template_id "
            "LEFT JOIN stations s ON s.id=g.station_id "
            "WHERE g.brand=?"
        )
        params: list = [brand]

        for arg, col in (("template_id", "g.template_id"), ("station_id", "g.station_id")):
            v = (request.args.get(arg) or "").strip()
            if v:
                try:
                    params.append(int(v)); sql += f" AND {col}=?"
                except ValueError:
                    pass
        status = (request.args.get("status") or "").strip().lower()
        if status:
            sql += " AND g.status=?"
            params.append(status)
        sql += " ORDER BY g.created_at DESC, g.id DESC LIMIT 200"

        conn = get_conn(); cur = conn.cursor()
        items = _rows(cur, sql, tuple(params))
        conn.close()
        return jsonify({"ok": True, "generated": items})

    @app.get("/admin/docx/generated/<int:gen_id>")
    @login_required
    def docx_generated_detail(gen_id: int):
        _admin_or_403()
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        gen = _row(cur,
            "SELECT g.*, t.name AS template_name, t.code AS template_code, t.module AS template_module, "
            "       s.name AS station_name, s.code AS station_code "
            "FROM docx_generated_documents g "
            "LEFT JOIN docx_templates t ON t.id=g.template_id "
            "LEFT JOIN stations s ON s.id=g.station_id "
            "WHERE g.id=? AND g.brand=?",
            (gen_id, brand),
        )
        if not gen:
            conn.close(); abort(404)
        try:
            gen["values"] = json.loads(gen.get("field_values_json") or "{}")
        except Exception:
            gen["values"] = {}
        conn.close()
        return jsonify({"ok": True, "generated": gen})

    @app.get("/admin/docx/generated/<int:gen_id>/download")
    @login_required
    def docx_generated_download(gen_id: int):
        me = _admin_or_403()
        brand = get_brand()
        prefer_pdf = request.args.get("format", "").lower() == "pdf"
        conn = get_conn(); cur = conn.cursor()
        gen = _row(cur, "SELECT * FROM docx_generated_documents WHERE id=? AND brand=?", (gen_id, brand))
        conn.close()
        if not gen:
            abort(404)
        target_rel = gen.get("pdf_path") if (prefer_pdf and gen.get("pdf_path")) else gen.get("docx_path")
        if not target_rel:
            abort(404, description="document_file_missing")
        try:
            ctx.log_action(me, "docx_generated_download", "docx_generated_documents", str(gen_id),
                           {"format": "pdf" if prefer_pdf and gen.get("pdf_path") else "docx"})
        except Exception:
            pass
        return storage.send(target_rel, as_attachment=True)

    @app.post("/admin/docx/generated/<int:gen_id>/approve")
    @login_required
    def docx_generated_approve(gen_id: int):
        me = _admin_or_403()
        return _transition_status(me, gen_id, "aprobado")

    @app.post("/admin/docx/generated/<int:gen_id>/cancel")
    @login_required
    def docx_generated_cancel(gen_id: int):
        me = _admin_or_403()
        body = request.get_json(silent=True) or {}
        reason = (body.get("reason") or "").strip() or None
        return _transition_status(me, gen_id, "cancelado", reason=reason)

    def _transition_status(me: dict, gen_id: int, target: str, *, reason: str | None = None):
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        gen = _row(cur, "SELECT * FROM docx_generated_documents WHERE id=? AND brand=?", (gen_id, brand))
        if not gen:
            conn.close(); abort(404)
        current = (gen.get("status") or "").lower()
        if not _can_transition(current, target):
            conn.close()
            return jsonify({
                "ok": False, "error": "invalid_transition",
                "message": f"No se puede pasar de '{current}' a '{target}'.",
            }), 400

        fields = ["status=?"]; params: list[Any] = [target]
        if target == "aprobado":
            fields += ["approved_by=?", "approved_at=?"]
            params += [int(me["id"]), _now_iso()]
        if target == "cancelado":
            fields += ["cancellation_reason=?"]
            params += [reason]
        params.append(gen_id)
        cur.execute(f"UPDATE docx_generated_documents SET {', '.join(fields)} WHERE id=?", tuple(params))
        conn.commit(); conn.close()

        try:
            ctx.log_action(me, f"docx_generated_{target}", "docx_generated_documents", str(gen_id),
                           {"reason": reason} if reason else {})
        except Exception:
            pass
        return jsonify({"ok": True, "status": target})

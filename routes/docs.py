from __future__ import annotations

from pathlib import Path

from flask import request, jsonify, current_app, render_template

from db import get_conn
from services.brand import get_brand


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    def _station_scope_ids(me: dict) -> list[int]:
        return sorted(int(x) for x in ctx.station_scope_ids(me))

    def _allowed_pending_exts() -> set[str]:
        return {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".xls", ".xlsx"}

    def _pending_docs_page_data(me: dict, is_admin: bool):
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        if is_admin or ctx.has_global_station_scope(me):
            cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY name ASC", (brand,))
        else:
            scope_ids = _station_scope_ids(me)
            if scope_ids:
                qmarks = ",".join(["?"] * len(scope_ids))
                cur.execute(f"SELECT id, code, name FROM stations WHERE brand=? AND id IN ({qmarks}) ORDER BY name ASC", (brand, *scope_ids))
            else:
                cur.execute("SELECT id, code, name FROM stations WHERE 1=0")
        stations = [dict(r) for r in cur.fetchall()]
        conn.close()
        default_station_id = stations[0]["id"] if len(stations) == 1 else ""
        return stations, default_station_id

    def _pending_group_key(brand: str, station_id: int | None, title: str) -> str:
        sid_part = str(station_id) if station_id is not None else "global"
        clean = " ".join((title or "").strip().lower().split())
        return f"{brand}:{sid_part}:general:pending_docs:{clean}"

    @app.get("/api/docs")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_docs_list():
        me = ctx.get_me() or {}
        module = (request.args.get("module") or "").strip() or "sasisopa"
        section = (request.args.get("section") or "").strip() or "general"
        show_all = (request.args.get("all") or "").strip().lower() in {"1", "true", "yes"}
        q = (request.args.get("q") or "").strip()

        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()

        sql = (
            "SELECT d.id, d.module, d.section, d.title, d.file_path, d.created_by, d.created_at, d.station_id, d.group_key, d.version_no, d.is_current, d.status, dv.expires_at, s.code AS station_code, s.name AS station_name "
            "FROM documents d "
            "LEFT JOIN document_versions dv ON dv.brand=d.brand AND dv.doc_group_key=d.group_key AND dv.version_no=d.version_no "
            "LEFT JOIN stations s ON s.id=d.station_id "
            "WHERE d.module=? AND d.section=? AND d.brand=? AND (d.is_current=1 OR ?=1)"
        )
        params: list = [module, section, brand, 1 if show_all else 0]

        if me.get('role') != 'admin':
            sql += " AND d.status='approved'"
        if q:
            like = f"%{q}%"
            sql += " AND (d.title LIKE ? OR COALESCE(s.name,'') LIKE ? OR COALESCE(s.code,'') LIKE ?)"
            params.extend([like, like, like])

        station_q = request.args.get("station_id")
        if me.get("role") == "admin":
            if station_q:
                try:
                    sid = int(station_q)
                    sql += " AND (d.station_id IS NULL OR d.station_id=?)"
                    params.append(sid)
                except Exception:
                    pass
        else:
            scope = _station_scope_ids(me)
            if not scope:
                conn.close()
                return jsonify({"ok": False, "error": "station_required"}), 400
            qmarks = ",".join(["?"] * len(scope))
            sql += f" AND d.station_id IN ({qmarks})"
            params.extend(scope)

        sql += " ORDER BY d.id DESC"
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.get("/api/docs/history")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_docs_history():
        """Return version history for a document group.

        Params: group_key=<...>
        """
        me = ctx.get_me() or {}
        gk = (request.args.get("group_key") or "").strip()
        if not gk:
            return jsonify({"ok": False, "error": "missing_group_key"}), 400

        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT module, station_id FROM documents WHERE brand=? AND group_key=? ORDER BY version_no DESC LIMIT 1",
            (brand, gk),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        # station users can only see history of their own station documents
        if me.get("role") != "admin":
            sid = row["station_id"]
            if sid is None or not ctx.can_access_station(me, int(sid)):
                conn.close();
                return jsonify({"ok": False, "error": "forbidden"}), 403

        cur.execute(
            """
            SELECT id, version_no, file_path, title, created_by, created_at, expires_at
            FROM document_versions
            WHERE brand=? AND doc_group_key=?
            ORDER BY version_no DESC
            """,
            (brand, gk),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": items})



    @app.get("/admin/shared-folder")
    @login_required
    @role_required("admin")
    def admin_shared_folder_page():
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY name ASC", (brand,))
        stations = [dict(r) for r in cur.fetchall()]
        conn.close()
        return render_template("shared_folder.html", me=ctx.get_me(), stations=stations, is_admin=True, default_station_id="", page_title="Carpeta compartida por estación", page_subtitle="Admin puede ver todas las carpetas por estación, subir documentos y descargar historial.", folder_module="general", folder_section="shared")

    @app.get("/staff/shared-folder")
    @login_required
    @role_required("jefe_estacion", "operador", "auditor", "contador")
    def staff_shared_folder_page():
        me = ctx.get_me() or {}
        brand = get_brand()
        scope_ids = _station_scope_ids(me)
        stations = []
        conn = get_conn(); cur = conn.cursor()
        if scope_ids:
            qmarks = ",".join(["?"] * len(scope_ids))
            cur.execute(f"SELECT id, code, name FROM stations WHERE brand=? AND id IN ({qmarks}) ORDER BY name ASC", (brand, *scope_ids))
            stations = [dict(r) for r in cur.fetchall()]
        conn.close()
        default_station_id = stations[0]["id"] if len(stations) == 1 else ""
        return render_template("shared_folder.html", me=me, stations=stations, is_admin=False, default_station_id=default_station_id, page_title="Mi carpeta compartida", page_subtitle="Solo puedes ver y subir documentos de tu estación o estaciones asignadas.", folder_module="general", folder_section="shared")

    @app.get("/admin/pending-docs")
    @login_required
    @role_required("admin")
    def admin_pending_docs_page():
        me = ctx.get_me() or {}
        stations, default_station_id = _pending_docs_page_data(me, True)
        return render_template(
            "pending_docs.html",
            me=me,
            stations=stations,
            is_admin=True,
            default_station_id=default_station_id,
            page_title="Documentos faltantes por validar",
            page_subtitle="Las estaciones suben documentos faltantes y administración los revisa, aprueba o rechaza.",
        )

    @app.get("/staff/pending-docs")
    @login_required
    @role_required("jefe_estacion", "operador", "auditor", "contador")
    def staff_pending_docs_page():
        me = ctx.get_me() or {}
        stations, default_station_id = _pending_docs_page_data(me, False)
        return render_template(
            "pending_docs.html",
            me=me,
            stations=stations,
            is_admin=False,
            default_station_id=default_station_id,
            page_title="Documentos faltantes",
            page_subtitle="Sube el documento faltante de tu estación. El administrador lo revisa y valida.",
        )

    @app.get("/api/docs/pending")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_pending_docs_list():
        me = ctx.get_me() or {}
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "").strip().lower()
        station_q = (request.args.get("station_id") or "").strip()
        show_all = (request.args.get("all") or "").strip().lower() in {"1", "true", "yes"}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        sql = (
            "SELECT d.id, d.title, d.file_path, d.created_at, d.created_by, d.station_id, d.group_key, d.version_no, d.is_current, d.status, d.change_reason, d.review_comment, d.approved_by, d.approved_at, "
            "s.code AS station_code, s.name AS station_name, u.username AS created_by_name, au.username AS approved_by_name "
            "FROM documents d "
            "LEFT JOIN stations s ON s.id=d.station_id "
            "LEFT JOIN users u ON u.id=d.created_by "
            "LEFT JOIN users au ON au.id=d.approved_by "
            "WHERE d.brand=? AND d.module='general' AND d.section='pending_docs' AND (d.is_current=1 OR ?=1)"
        )
        params = [brand, 1 if show_all else 0]
        if status in {"pending", "approved", "rejected"}:
            sql += " AND LOWER(d.status)=?"
            params.append(status)
        if q:
            like = f"%{q}%"
            sql += " AND (d.title LIKE ? OR COALESCE(d.change_reason,'') LIKE ? OR COALESCE(d.review_comment,'') LIKE ? OR COALESCE(s.name,'') LIKE ? OR COALESCE(s.code,'') LIKE ?)"
            params.extend([like, like, like, like, like])
        if me.get("role") == "admin":
            if station_q:
                try:
                    sid = int(station_q)
                    sql += " AND d.station_id=?"
                    params.append(sid)
                except Exception:
                    conn.close()
                    return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        else:
            scope = _station_scope_ids(me)
            if not scope:
                conn.close()
                return jsonify({"ok": False, "error": "station_required"}), 400
            if station_q:
                try:
                    sid = int(station_q)
                except Exception:
                    conn.close()
                    return jsonify({"ok": False, "error": "invalid_station_id"}), 400
                if sid not in scope:
                    conn.close()
                    return jsonify({"ok": False, "error": "forbidden"}), 403
                scope = [sid]
            qmarks = ",".join(["?"] * len(scope))
            sql += f" AND d.station_id IN ({qmarks})"
            params.extend(scope)
        sql += " ORDER BY CASE LOWER(d.status) WHEN 'pending' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END, d.created_at DESC, d.id DESC"
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.post("/api/docs/pending/upload")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "contador", "auditor")
    def api_pending_docs_upload():
        me = ctx.get_me() or {}
        title = (request.form.get("title") or "").strip()
        station_id = (request.form.get("station_id") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None
        if not title:
            return jsonify({"ok": False, "error": "missing_title"}), 400
        try:
            station_id_int = int(station_id)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        if me.get("role") != "admin":
            scope = _station_scope_ids(me)
            if not scope or station_id_int not in scope:
                return jsonify({"ok": False, "error": "forbidden"}), 403
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE id=? AND brand=?", (station_id_int, brand))
        st = cur.fetchone()
        if not st:
            conn.close()
            return jsonify({"ok": False, "error": "station_not_found"}), 404
        f = request.files.get("file")
        if not f or not (f.filename or "").strip():
            conn.close()
            return jsonify({"ok": False, "error": "missing_file"}), 400
        try:
            relpath = ctx.save_upload_checked(
                f,
                "docs/general/pending_docs",
                allowed_ext=_allowed_pending_exts(),
                limit_mb=int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20)),
                allowed_magic=None,
            )
        except ValueError as ex:
            conn.close()
            return jsonify({"ok": False, "error": str(ex) or "invalid_file_type"}), 400
        if not relpath:
            conn.close()
            return jsonify({"ok": False, "error": "save_failed"}), 400

        doc_group_key = _pending_group_key(brand, station_id_int, title)
        cur.execute("UPDATE documents SET is_current=0 WHERE brand=? AND group_key=?", (brand, doc_group_key))
        cur.execute("SELECT MAX(version_no) AS m FROM document_versions WHERE brand=? AND doc_group_key=?", (brand, doc_group_key))
        rmax = cur.fetchone()
        ver = int((rmax["m"] or 0)) + 1 if rmax else 1
        cur.execute(
            """INSERT INTO documents (module, section, title, file_path, created_by, station_id, brand, group_key, version_no, is_current, status, change_reason, review_comment, approved_by, approved_at, effective_at)
                 VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)""",
            ("general", "pending_docs", title, relpath, me.get("id"), station_id_int, brand, doc_group_key, ver, "pending", notes, None, None, None, None),
        )
        doc_id = int(cur.lastrowid)
        cur.execute(
            """INSERT INTO document_versions (doc_group_key, version_no, document_id, file_path, title, module, section, station_id, brand, created_by, expires_at, status, change_reason, review_comment, approved_by, approved_at, effective_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_group_key, ver, doc_id, relpath, title, "general", "pending_docs", station_id_int, brand, me.get("id"), None, "pending", notes, None, None, None, None),
        )
        conn.commit(); conn.close()
        ctx.log_action(me, "upload_pending_doc", "documents", str(doc_id), {"station_id": station_id_int, "title": title, "version": ver})
        ctx.notify_admins(
            "Documento por validar",
            f"{title} · {(st['code'] or '')} {(st['name'] or '')}".strip(),
            "/admin/pending-docs",
            station_id=station_id_int,
            exclude_user_id=me.get("id"),
            ntype="pending_doc_review",
            brand=brand,
        )
        return jsonify({"ok": True, "id": doc_id, "file_path": relpath, "version": ver})

    @app.post("/api/docs/pending/<int:doc_id>/review")
    @login_required
    @role_required("admin")
    def api_pending_docs_review(doc_id: int):
        me = ctx.get_me() or {}
        payload = request.get_json(silent=True) or request.form or {}
        action = (payload.get("status") or payload.get("action") or "").strip().lower()
        if action not in {"approved", "rejected"}:
            return jsonify({"ok": False, "error": "invalid_status"}), 400
        review_comment = (payload.get("review_comment") or payload.get("comment") or "").strip() or None
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id=? AND brand=? AND module='general' AND section='pending_docs'", (doc_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404
        now_iso = ctx.now_iso()
        approved_by = me.get("id") if action == "approved" else None
        approved_at = now_iso if action == "approved" else None
        effective_at = now_iso if action == "approved" else None
        cur.execute(
            "UPDATE documents SET status=?, review_comment=?, approved_by=?, approved_at=?, effective_at=? WHERE id=? AND brand=?",
            (action, review_comment, approved_by, approved_at, effective_at, doc_id, brand),
        )
        cur.execute(
            "UPDATE document_versions SET status=?, review_comment=?, approved_by=?, approved_at=?, effective_at=? WHERE brand=? AND doc_group_key=? AND version_no=?",
            (action, review_comment, approved_by, approved_at, effective_at, brand, row["group_key"], row["version_no"]),
        )
        conn.commit(); conn.close()
        ctx.log_action(me, "review_pending_doc", "documents", str(doc_id), {"status": action, "station_id": row["station_id"]})
        rowd = dict(row)
        if rowd.get("created_by"):
            title = "Documento validado" if action == "approved" else "Documento rechazado"
            body = (rowd.get("title") or "Documento")
            if review_comment:
                body = f"{body} · {review_comment}"
            ctx.notify(int(rowd["created_by"]), rowd["station_id"], title, body, "/staff/pending-docs", ntype="pending_doc_result", brand=brand)
        if rowd.get("station_id"):
            ctx.notify_station_chiefs(int(rowd["station_id"]), "Validación de documento", f"{rowd.get('title') or 'Documento'} · {'Aprobado' if action == 'approved' else 'Rechazado'}", "/staff/pending-docs", exclude_user_id=me.get("id"), ntype="pending_doc_result", brand=brand)
        return jsonify({"ok": True})

    @app.get("/admin/document-center")
    @login_required
    @role_required("admin")
    def admin_document_center_page():
        return render_template("admin/document_center.html", me=ctx.get_me())

    @app.get("/api/admin/document-center")
    @login_required
    @role_required("admin")
    def api_admin_document_center():
        brand = get_brand()
        q = (request.args.get("q") or "").strip()
        station_id = (request.args.get("station_id") or "").strip()
        module = (request.args.get("module") or "").strip().lower()
        conn = get_conn(); cur = conn.cursor()

        params = [brand]
        where = ["d.brand=?"]
        if module:
            where.append("LOWER(d.module)=?")
            params.append(module)
        if station_id:
            try:
                sid = int(station_id)
                where.append("(d.station_id IS NULL OR d.station_id=?)")
                params.append(sid)
            except Exception:
                conn.close()
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        if q:
            like = f"%{q}%"
            where.append("(d.title LIKE ? OR d.section LIKE ? OR COALESCE(s.name,'') LIKE ? OR COALESCE(s.code,'') LIKE ?)")
            params.extend([like, like, like, like])

        cur.execute(
            """
            SELECT d.id, d.module, d.section, d.title, d.station_id, d.group_key, d.version_no, d.status, d.is_current, d.created_at,
                   dv.expires_at, s.code AS station_code, s.name AS station_name
            FROM documents d
            LEFT JOIN document_versions dv ON dv.brand=d.brand AND dv.doc_group_key=d.group_key AND dv.version_no=d.version_no
            LEFT JOIN stations s ON s.id=d.station_id
            WHERE """ + " AND ".join(where) + " ORDER BY d.created_at DESC, d.id DESC LIMIT 500",
            tuple(params),
        )
        docs = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT ds.id, ds.module, ds.review_status, ds.submitted_at, ds.reviewed_at, dr.title AS requirement_title,
                   dr.station_id AS station_id, st.code AS station_code, st.name AS station_name, u.username AS operator_name
            FROM doc_submissions ds
            JOIN doc_requirements dr ON dr.id=ds.requirement_id AND dr.brand=ds.brand AND dr.module=ds.module
            LEFT JOIN stations st ON st.id=dr.station_id
            LEFT JOIN users u ON u.id=ds.operator_id
            WHERE ds.brand=?
            ORDER BY ds.submitted_at DESC, ds.id DESC LIMIT 300
            """,
            (brand,),
        )
        submissions = [dict(r) for r in cur.fetchall()]
        conn.close()

        if module:
            submissions = [r for r in submissions if (r.get("module") or "").lower() == module]
        if station_id:
            sid_s = str(station_id)
            submissions = [r for r in submissions if sid_s in {str(r.get('station_id') or ''), str(r.get('station_code') or '')}]
        if q:
            ql = q.lower()
            submissions = [r for r in submissions if ql in ((r.get("requirement_title") or "").lower() + " " + (r.get("station_name") or "").lower() + " " + (r.get("operator_name") or "").lower())]

        summary = {
            "docs_total": len(docs),
            "docs_current": sum(1 for d in docs if int(d.get("is_current") or 0) == 1),
            "docs_expiring": sum(1 for d in docs if d.get("expires_at")),
            "submissions_pending": sum(1 for s in submissions if (s.get("review_status") or "").upper() == "PENDING"),
            "submissions_wrong": sum(1 for s in submissions if (s.get("review_status") or "").upper() == "WRONG"),
            "submissions_correct": sum(1 for s in submissions if (s.get("review_status") or "").upper() == "CORRECT"),
        }
        return jsonify({"ok": True, "summary": summary, "docs": docs, "submissions": submissions})

    @app.post("/api/docs/upload")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_docs_upload():
        me = ctx.get_me() or {}
        module = (request.form.get("module") or "").strip() or "sasisopa"
        # For now, Calibraciones uploads are admin-only.
        if (module or "").strip().lower() == "calibraciones" and me.get("role") != "admin":
            return jsonify({"ok": False, "error": "forbidden"}), 403

        section = (request.form.get("section") or "").strip() or "general"
        title = (request.form.get("title") or "").strip() or None
        if not title:
            return jsonify({"ok": False, "error": "missing_title", "message": "El campo title es obligatorio"}), 400

        allowed_modules = {"sasisopa", "sgm", "calibraciones", "general"}
        if (module or "").lower() not in allowed_modules:
            return jsonify({"ok": False, "error": "invalid_module"}), 400
        if not section:
            return jsonify({"ok": False, "error": "invalid_section"}), 400

        station_id = request.form.get("station_id")
        if station_id not in (None, "", "null"):
            try:
                station_id = int(station_id)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        else:
            station_id = None

        is_admin = me.get("role") == "admin"
        if not is_admin:
            if (module or "").strip().lower() != "general" or (section or "").strip().lower() != "shared":
                return jsonify({"ok": False, "error": "forbidden"}), 403
            scope = _station_scope_ids(me)
            if not scope:
                return jsonify({"ok": False, "error": "station_required"}), 400
            if station_id is None:
                if len(scope) == 1:
                    station_id = scope[0]
                else:
                    return jsonify({"ok": False, "error": "station_id_required"}), 400
            if int(station_id) not in scope:
                return jsonify({"ok": False, "error": "forbidden"}), 403

        if station_id is not None:
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM stations WHERE id=?", (int(station_id),))
            ok = cur.fetchone() is not None
            conn.close()
            if not ok:
                return jsonify({"ok": False, "error": "station_not_found"}), 404

        brand = get_brand()
        f = request.files.get("file")
        if not f or not (f.filename or "").strip():
            return jsonify({"ok": False, "error": "missing_file"}), 400

        section_lower = (section or "").lower()
        is_annual = ("anual" in section_lower) or ("annual" in section_lower)
        limit = int(
            current_app.config.get(
                "UPLOAD_LIMIT_ANNUAL_MB" if is_annual else "UPLOAD_LIMIT_DEFAULT_MB",
                120 if is_annual else 20,
            )
        )

        relpath = ctx.save_upload_checked(
            f,
            f"docs/{module}/{section}",
            allowed_ext={".pdf"},
            allowed_magic={"pdf"},
            limit_mb=limit,
        )
        if not relpath:
            return jsonify({"ok": False, "error": "save_failed"}), 400

        # Versioning: group docs by (brand, station_id, module, section, title)
        sid_part = str(station_id) if station_id is not None else "global"
        doc_group_key = f"{brand}:{sid_part}:{(module or '').lower()}:{(section or '').lower()}:{(title or '').strip().lower()}"

        change_reason = (request.form.get("change_reason") or "").strip() or None

        expires_at = (request.form.get("expires_at") or "").strip() or None
        if expires_at:
            # expect YYYY-MM-DD
            try:
                __import__("datetime").date.fromisoformat(expires_at[:10])
            except Exception:
                return jsonify({"ok": False, "error": "invalid_expires_at"}), 400

        conn = get_conn(); cur = conn.cursor()

        # Mark previous current doc(s) as non-current
        cur.execute("UPDATE documents SET is_current=0 WHERE brand=? AND group_key=?", (brand, doc_group_key))

        # Next version number
        cur.execute(
            "SELECT MAX(version_no) AS m FROM document_versions WHERE brand=? AND doc_group_key=?",
            (brand, doc_group_key),
        )
        rmax = cur.fetchone()
        ver = int((rmax["m"] or 0)) + 1 if rmax else 1

        cur.execute(
            """INSERT INTO documents (module, section, title, file_path, created_by, station_id, brand, group_key, version_no, is_current, status, change_reason, approved_by, approved_at, effective_at)
                 VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
            (module, section, title, relpath, me.get("id"), station_id, brand, doc_group_key, ver, 'approved', change_reason, me.get('id'), ctx.now_iso(), ctx.now_iso()),
        )
        doc_id = cur.lastrowid

        # Mirror into document_versions table (history)
        cur.execute(
            """INSERT INTO document_versions (doc_group_key, version_no, document_id, file_path, title, module, section, station_id, brand, created_by, expires_at, status, change_reason, approved_by, approved_at, effective_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_group_key, ver, doc_id, relpath, title, module, section, station_id, brand, me.get("id"), expires_at, 'approved', change_reason, me.get('id'), ctx.now_iso(), ctx.now_iso()),
        )

        conn.commit(); conn.close()

        ctx.log_action(me, "upload_doc", "documents", str(doc_id), {"module": module, "section": section, "file": relpath, "station_id": station_id, "version": ver, "expires_at": expires_at})
        ctx.sign_entity(me, "document", str(doc_id), "uploaded", {"module": module, "section": section, "station_id": station_id, "version": ver, "expires_at": expires_at})

        # Notify users about updates in compliance modules (SASISOPA/SGM).
        # Calibraciones will get its own alert flow later, so keep it silent for now.
        mod_lower = (module or "").strip().lower()
        sec_lower = (section or "").strip().lower()
        if mod_lower in {"sasisopa", "sgm"}:
            url_target = "/admin/sasisopa" if mod_lower == "sasisopa" else f"/admin/{mod_lower}"
            if station_id is None:
                ctx.notify(None, None, f"Documento actualizado ({mod_lower.upper()})", title or "Documento", url_target)
            else:
                ctx.notify_admins_and_station_chiefs(int(station_id), f"Documento actualizado ({mod_lower.upper()})", title or "Documento", url_target, exclude_user_id=me.get("id"))
        elif mod_lower == "general" and sec_lower == "shared" and station_id is not None:
            ctx.notify_admins_and_station_chiefs(int(station_id), "Carpeta compartida actualizada", title or "Documento compartido", "/admin/shared-folder", exclude_user_id=me.get("id"))

        return jsonify({"ok": True, "id": doc_id, "file_path": relpath, "version": ver, "url": f"/uploads/{relpath}"})

    @app.post("/api/docs/upload-batch")
    @login_required
    @role_required("admin")
    def api_docs_upload_batch():
        me = ctx.get_me() or {}
        module = (request.form.get("module") or "general").strip().lower() or "general"
        section = (request.form.get("section") or "general").strip() or "general"
        station_id_raw = (request.form.get("station_id") or "").strip()
        expires_at = (request.form.get("expires_at") or "").strip() or None
        station_id = None
        if station_id_raw:
            try:
                station_id = int(station_id_raw)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        files = request.files.getlist("files") or request.files.getlist("files[]")
        if not files:
            return jsonify({"ok": False, "error": "missing_files"}), 400
        brand = get_brand()
        created = []
        for f in files[:20]:
            if not f or not (f.filename or "").strip():
                continue
            title = (request.form.get(f"title__{f.filename}") or Path(f.filename).stem).strip()
            # simulate same logic as single upload using the current request context object
            # by storing file directly and versioning per title.
            relpath = ctx.save_upload_checked(f, f"docs/{module}/{section}", allowed_ext={".pdf"}, allowed_magic={"pdf"}, limit_mb=int(current_app.config.get("UPLOAD_LIMIT_DEFAULT_MB", 20)))
            sid_part = str(station_id) if station_id is not None else "global"
            doc_group_key = f"{brand}:{sid_part}:{module}:{section.lower()}:{title.lower()}"
            conn = get_conn(); cur = conn.cursor()
            cur.execute("UPDATE documents SET is_current=0 WHERE brand=? AND group_key=?", (brand, doc_group_key))
            cur.execute("SELECT MAX(version_no) AS m FROM document_versions WHERE brand=? AND doc_group_key=?", (brand, doc_group_key))
            rmax = cur.fetchone(); ver = int((rmax["m"] or 0)) + 1 if rmax else 1
            cur.execute("INSERT INTO documents (module, section, title, file_path, created_by, station_id, brand, group_key, version_no, is_current, status, approved_by, approved_at, effective_at) VALUES (?,?,?,?,?,?,?,?,?,1,'approved',?,?,?)", (module, section, title, relpath, me.get("id"), station_id, brand, doc_group_key, ver, me.get("id"), ctx.now_iso(), ctx.now_iso()))
            doc_id = int(cur.lastrowid)
            cur.execute("INSERT INTO document_versions (doc_group_key, version_no, document_id, file_path, title, module, section, station_id, brand, created_by, expires_at, status, approved_by, approved_at, effective_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (doc_group_key, ver, doc_id, relpath, title, module, section, station_id, brand, me.get("id"), expires_at, 'approved', me.get('id'), ctx.now_iso(), ctx.now_iso()))
            conn.commit(); conn.close()
            ctx.log_action(me, "upload_doc_batch_item", "documents", str(doc_id), {"module": module, "section": section, "file": relpath, "station_id": station_id, "version": ver})
            ctx.sign_entity(me, "document", str(doc_id), "uploaded_batch", {"module": module, "section": section, "station_id": station_id, "version": ver})
            created.append({"id": doc_id, "title": title, "version": ver, "file_path": relpath})
        return jsonify({"ok": True, "items": created, "count": len(created)})

    @app.post("/api/docs/<int:doc_id>/restore")
    @login_required
    @role_required("admin")
    def api_docs_restore(doc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, group_key, station_id, module, title, section FROM documents WHERE id=? AND brand=?", (doc_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404

        gk = row["group_key"]
        if not gk:
            conn.close()
            return jsonify({"ok": False, "error": "missing_group_key"}), 400

        cur.execute("UPDATE documents SET is_current=0 WHERE brand=? AND group_key=?", (brand, gk))
        cur.execute("UPDATE documents SET is_current=1 WHERE id=? AND brand=?", (int(doc_id), brand))
        conn.commit(); conn.close()

        ctx.log_action(me, "restore_doc_version", "documents", str(doc_id), {"group_key": gk})
        ctx.sign_entity(me, "document", str(doc_id), "restored", {"group_key": gk})

        mod_lower = (row["module"] or "").lower()
        url_target = "/admin/sasisopa" if mod_lower == "sasisopa" else f"/admin/{mod_lower}" if mod_lower else "/admin"
        if row["station_id"] is None:
            ctx.notify(None, None, f"Documento restaurado ({mod_lower.upper()})", row["title"] or "Documento", url_target)
        else:
            ctx.notify_admins_and_station_chiefs(int(row["station_id"]), f"Documento restaurado ({mod_lower.upper()})", row["title"] or "Documento", url_target, exclude_user_id=me.get("id"))

        return jsonify({"ok": True})

    
    @app.post("/api/docs/<int:doc_id>/obsolete")
    @login_required
    @role_required("admin")
    def api_docs_obsolete(doc_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, group_key FROM documents WHERE id=? AND brand=?", (doc_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404
        gk = row["group_key"]
        if not gk:
            conn.close()
            return jsonify({"ok": False, "error": "missing_group_key"}), 400

        now_iso = ctx.now_iso()
        cur.execute("UPDATE documents SET status='obsolete', obsolete_at=?, is_current=0 WHERE brand=? AND group_key=?", (now_iso, brand, gk))
        cur.execute("UPDATE document_versions SET status='obsolete', obsolete_at=? WHERE brand=? AND doc_group_key=?", (now_iso, brand, gk))
        conn.commit(); conn.close()

        ctx.log_action(me, "obsolete_doc", "documents", str(doc_id), {"group_key": gk})
        ctx.sign_entity(me, "document", str(doc_id), "obsolete", {"group_key": gk})
        return jsonify({"ok": True})

    @app.delete("/api/docs/<int:doc_id>")
    @login_required
    @role_required("admin")
    def api_docs_delete(doc_id: int):
        me = ctx.get_me() or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT file_path FROM documents WHERE id=?", (doc_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404
        cur.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit(); conn.close()

        # File is left on disk to avoid accidental data loss
        ctx.log_action(me, "delete_doc", "documents", str(doc_id), {"file": row["file_path"]})
        return jsonify({"ok": True})

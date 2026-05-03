from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from calendar import monthrange

try:
    import pymupdf as fitz
except Exception:  # pragma: no cover
    import fitz

from flask import abort, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from db import get_conn
from services.brand import set_brand, parse_allowed_brands, get_brand
from services.corrections import create_correction_task
from services.storage import get_storage


def register_module(app, *, brand: str | None = None, module_key: str, module_label: str, template_folder: str = "documental_docs", route_segment: str | None = None):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    route_segment = route_segment or module_key
    upload_dir = Path(ctx.upload_dir)
    storage = app.extensions["storage"]
    admin_base = f"/admin/{route_segment}/docs"
    staff_base = f"/staff/{route_segment}/docs"

    def _brand() -> str:
        fixed = (brand or "").strip().lower() if isinstance(brand, str) else ""
        if fixed in {"consulting", "petroleum"}:
            return fixed
        try:
            current = (get_brand() or "consulting").strip().lower()
        except Exception:
            current = "consulting"
        return current if current in {"consulting", "petroleum"} else "consulting"

    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _today() -> date:
        return date.today()

    def _add_months(dt_obj: datetime, months: int = 2) -> datetime:
        y = dt_obj.year + ((dt_obj.month - 1 + months) // 12)
        m = ((dt_obj.month - 1 + months) % 12) + 1
        d = min(dt_obj.day, monthrange(y, m)[1])
        return dt_obj.replace(year=y, month=m, day=d)

    def _template_relpath(month_key: str, filename: str) -> str:
        return f"{module_key}_templates/{_brand()}/{month_key}/{filename}"

    def _template_abspath(relpath: str) -> Path:
        return storage.ensure_local(relpath)

    def _preview_relpath(template_id: int, page_no: int) -> str:
        return f"{module_key}_template_previews/{_brand()}/{template_id}/page_{page_no + 1}.png"

    def _ensure_template_previews(template_id: int, file_path: str) -> list[str]:
        src = _template_abspath(file_path)
        out_dir = upload_dir / f"{module_key}_template_previews/{_brand()}/{template_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        previews: list[str] = []
        if not src.exists():
            return previews
        doc = fitz.open(src)
        try:
            for i in range(len(doc)):
                out_rel = _preview_relpath(template_id, i)
                out_abs = upload_dir / out_rel
                if not storage.exists(out_rel):
                    out_abs.parent.mkdir(parents=True, exist_ok=True)
                    pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
                    pix.save(out_abs)
                    storage.upload_local_file(out_abs, out_rel, content_type="image/png")
                previews.append(out_rel)
        finally:
            doc.close()
        return previews

    def _load_schema(row) -> list[dict]:
        raw = row["field_schema_json"] if row and row["field_schema_json"] else "[]"
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _json_dumps(data) -> str:
        return json.dumps(data, ensure_ascii=False)

    def _parse_schema_input(text: str) -> list[dict]:
        data = json.loads(text or "[]")
        if not isinstance(data, list):
            raise ValueError("El esquema debe ser una lista JSON")
        cleaned: list[dict] = []
        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"Fila {idx}: cada campo debe ser un objeto JSON")
            key = str(item.get("key") or "").strip()
            label = str(item.get("label") or key or f"Campo {idx}").strip()
            if not key:
                raise ValueError(f"Fila {idx}: falta key")
            page = int(item.get("page", 0))
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
            w = float(item.get("w", 220))
            h = float(item.get("h", 18))
            font_size = float(item.get("font_size", 10))
            max_len = int(item.get("max_len", 160))
            align = str(item.get("align") or "left").strip().lower()
            field_type = str(item.get("type") or "text").strip().lower()
            cleaned.append({
                "key": key,
                "label": label,
                "page": page,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "font_size": font_size,
                "max_len": max_len,
                "align": align if align in {"left", "center", "right"} else "left",
                "type": field_type if field_type in {"text", "textarea", "date", "number"} else "text",
                "placeholder": str(item.get("placeholder") or ""),
                "staff_editable": True if item.get("staff_editable") in {True, 1, "1", "true", "yes", "on"} else False,
            })
        return cleaned

    def _render_pdf(template_relpath: str, schema: list[dict], values: dict, out_relpath: str) -> None:
        src = storage.ensure_local(template_relpath)
        out = upload_dir / out_relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(src)
        try:
            for field in schema:
                page_no = int(field.get("page", 0))
                if page_no < 0 or page_no >= len(doc):
                    continue
                value = str(values.get(field["key"], "") or "").strip()
                if not value:
                    continue
                value = value[: int(field.get("max_len", 160))]
                page = doc.load_page(page_no)
                rect = fitz.Rect(
                    float(field.get("x", 0)),
                    float(field.get("y", 0)),
                    float(field.get("x", 0)) + float(field.get("w", 220)),
                    float(field.get("y", 0)) + float(field.get("h", 18)),
                )
                align_value = {"left": 0, "center": 1, "right": 2}.get(str(field.get("align", "left")), 0)
                page.insert_textbox(
                    rect,
                    value,
                    fontsize=float(field.get("font_size", 10)),
                    fontname="helv",
                    align=align_value,
                    color=(0, 0, 0),
                )
            doc.save(out, deflate=True)
            storage.upload_local_file(out, out_relpath, content_type="application/pdf")
        finally:
            doc.close()

    def _admin_required():
        me = ctx.get_me()
        if not me:
            abort(401)
        set_brand(_brand())
        if me.get("role") != "admin":
            abort(403)
        return me

    def _staff_allowed():
        me = ctx.get_me()
        if not me:
            abort(401)
        set_brand(_brand())
        if me.get("role") == "admin":
            return me
        allowed = parse_allowed_brands(me.get("allowed_brands"))
        if _brand() not in allowed:
            abort(403)
        return me

    def _get_template(conn, template_id: int):
        return conn.execute("SELECT * FROM doc_templates WHERE id=? AND brand=? AND module=?", (int(template_id), _brand(), module_key)).fetchone()

    def _get_requirement(conn, requirement_id: int):
        return conn.execute("""
            SELECT r.*, t.name AS template_name, t.file_path, t.field_schema_json
            FROM doc_requirements r
            JOIN doc_templates t ON t.id=r.template_id AND t.brand=r.brand AND t.module=r.module
            WHERE r.id=? AND r.brand=? AND r.module=?
        """, (int(requirement_id), _brand(), module_key)).fetchone()

    def _active_unlock(conn, requirement_id: int, operator_id: int):
        return conn.execute("""
            SELECT * FROM doc_unlocks
            WHERE brand=? AND module=? AND requirement_id=? AND operator_id=? AND is_active=1
            ORDER BY id DESC LIMIT 1
        """, (_brand(), module_key, int(requirement_id), int(operator_id))).fetchone()

    def _attempt_info(conn, requirement_id: int):
        """Return the latest submission for a requirement.

        Policy: only ONE submission is allowed per station/requirement (first one wins).
        """
        return conn.execute("""
            SELECT * FROM doc_submissions
            WHERE brand=? AND module=? AND requirement_id=?
            ORDER BY id DESC LIMIT 1
        """, (_brand(), module_key, int(requirement_id))).fetchone()
    def _compute_requirement_state(req, me, last_submission=None, unlock=None):
        # NOTE: Policy: staff can submit ONLY ONCE. No unlocks / no reattempts.
        today = _today()
        open_date = date.fromisoformat((req["open_date"] or str(today))[:10])
        due_date = date.fromisoformat((req["due_date"] or str(today))[:10])

        if last_submission:
            review_status = (last_submission["review_status"] or "PENDING").upper()
            if review_status == "CORRECT":
                return "Aprobado", False, "Documento aprobado"
            if review_status == "WRONG":
                return "Rechazado", False, "Documento rechazado. Solo el administrador puede volver a programar uno nuevo."
            return "En revisión", False, "Ya fue enviado; espera revisión del administrador"

        if today < open_date:
            return "Programado", False, f"Disponible desde {open_date.isoformat()}"
        if today > due_date:
            return "Vencido", False, "Fuera de fecha"
        return "Pendiente", True, f"Entrega máxima {due_date.isoformat()}"

    def _requirement_visible_to_user(me, req):
        if me.get("role") == "admin":
            return True
        assigned_user_id = req["assigned_user_id"]
        if assigned_user_id and int(assigned_user_id) != int(me["id"]):
            return False
        req_station = req["station_id"]
        if req_station:
            return int(req_station) == int(me.get("station_id") or -1)
        return True

    def _template_choices(conn):
        templates = [dict(r) for r in conn.execute("SELECT * FROM doc_templates WHERE brand=? AND module=? ORDER BY created_at DESC, id DESC", (_brand(), module_key)).fetchall()]
        for tpl in templates:
            tpl["field_count"] = len(_load_schema(tpl))
        return templates

    def _calendar_events_for_admin(conn):
        rows = [dict(r) for r in conn.execute("""
            SELECT r.id, r.title, r.open_date, r.due_date, r.status,
                   t.name AS template_name,
                   s.name AS station_name,
                   u.username AS assigned_user
            FROM doc_requirements r
            JOIN doc_templates t ON t.id=r.template_id AND t.brand=r.brand AND t.module=r.module
            LEFT JOIN stations s ON s.id=r.station_id
            LEFT JOIN users u ON u.id=r.assigned_user_id
            WHERE r.brand=? AND r.module=?
            ORDER BY r.open_date DESC, r.id DESC
        """, (_brand(), module_key)).fetchall()]
        events = []
        for row in rows:
            title = row["title"]
            if row.get("assigned_user"):
                title += f" • {row['assigned_user']}"
            elif row.get("station_name"):
                title += f" • {row['station_name']}"
            events.append({"id": row["id"], "title": title, "start": row["open_date"], "end": row["due_date"], "url": f"{admin_base}/reviews?requirement_id={row['id']}"})
        return rows, events

    def _visible_requirements(conn, me):
        rows = []
        for req in conn.execute("""
            SELECT r.*, t.name AS template_name, t.file_path, t.field_schema_json
            FROM doc_requirements r
            JOIN doc_templates t ON t.id=r.template_id AND t.brand=r.brand AND t.module=r.module
            WHERE r.brand=? AND r.module=?
            ORDER BY r.open_date DESC, r.id DESC
        """, (_brand(), module_key)).fetchall():
            reqd = dict(req)
            if not _requirement_visible_to_user(me, reqd):
                continue
            last = _attempt_info(conn, reqd["id"])
            unlock = None
            state, can_capture, helper = _compute_requirement_state(reqd, me, last_submission=last, unlock=unlock)
            reqd.update({"state": state, "can_capture": can_capture, "helper": helper})
            rows.append(reqd)
        return rows

    def _example_schema() -> str:
        return json.dumps([
            {"key": "fecha", "label": "Fecha", "page": 0, "x": 380, "y": 130, "w": 140, "h": 18, "font_size": 10, "max_len": 40, "align": "left", "type": "date", "placeholder": "2026-01-15", "staff_editable": true},
            {"key": "responsable", "label": "Responsable", "page": 0, "x": 130, "y": 210, "w": 250, "h": 18, "font_size": 10, "max_len": 90, "align": "left", "type": "text", "placeholder": "Nombre completo", "staff_editable": false},
        ], ensure_ascii=False, indent=2)

    def _base_context(**extra):
        brand_label = "Petroleum" if _brand() == "petroleum" else "Consulting"
        return {"module_key": module_key, "module_label": module_label, "admin_base": admin_base, "staff_base": staff_base, "brand": _brand(), "brand_label": brand_label, **extra}

    def _route(rule, endpoint, view_func, methods=("GET",)):
        app.add_url_rule(rule, endpoint=endpoint, view_func=login_required(view_func), methods=list(methods))

    def admin_dashboard():
        _admin_required()
        conn = get_conn(); requirements, events = _calendar_events_for_admin(conn)
        stats = {
            "templates": conn.execute("SELECT COUNT(*) AS c FROM doc_templates WHERE brand=? AND module=?", (_brand(), module_key)).fetchone()["c"],
            "requirements": conn.execute("SELECT COUNT(*) AS c FROM doc_requirements WHERE brand=? AND module=?", (_brand(), module_key)).fetchone()["c"],
            "pending": conn.execute("SELECT COUNT(*) AS c FROM doc_submissions WHERE brand=? AND module=? AND review_status='PENDING'", (_brand(), module_key)).fetchone()["c"],
        }
        conn.close()
        return render_template(f"{template_folder}/admin_dashboard.html", **_base_context(stats=stats, requirements=requirements[:12], calendar_events=events))
    def admin_board():
        _admin_required()
        day = (request.args.get("date") or "").strip()
        if not day:
            day = _today().isoformat()
        status_filter = (request.args.get("status") or "all").strip().lower()
        if status_filter not in {"all", "pending", "submitted", "approved", "rejected", "unplanned"}:
            status_filter = "all"
        q = (request.args.get("q") or "").strip()
        export_fmt = (request.args.get("export") or "").strip().lower()
        # Validate YYYY-MM-DD
        try:
            day_obj = datetime.fromisoformat(day)
            day = day[:10]
        except Exception:
            abort(400)

        conn = get_conn()
        stations = [dict(r) for r in conn.execute(
            "SELECT id, name, code FROM stations WHERE brand=? ORDER BY name ASC",
            (_brand(),),
        ).fetchall()]

        req_rows = conn.execute(
            """
            SELECT dr.*, dt.name AS template_name, u.username AS assigned_user
            FROM doc_requirements dr
            JOIN doc_templates dt ON dt.id=dr.template_id AND dt.brand=dr.brand AND dt.module=dr.module
            LEFT JOIN users u ON u.id=dr.assigned_user_id
            WHERE dr.brand=? AND dr.module=? AND dr.open_date=?
            """,
            (_brand(), module_key, day),
        ).fetchall()

        req_by_station = {}
        req_ids = []
        for r in req_rows:
            sid = int(r["station_id"]) if r["station_id"] else 0
            d = dict(r)
            req_by_station[sid] = d
            req_ids.append(int(d["id"]))

        sub_by_req = {}
        if req_ids:
            qmarks = ",".join(["?"] * len(req_ids))
            rows = conn.execute(
                f"""
                SELECT * FROM doc_submissions
                WHERE brand=? AND module=? AND requirement_id IN ({qmarks})
                ORDER BY requirement_id ASC, attempt_no DESC, id DESC
                """,
                [_brand(), module_key, *req_ids],
            ).fetchall()
            for r in rows:
                rid = int(r["requirement_id"])
                if rid not in sub_by_req:
                    sub_by_req[rid] = dict(r)

        def _label(st: str | None) -> str:
            st = (st or "").upper()
            return {
                "OPEN": "Pendiente",
                "SUBMITTED": "Enviado",
                "APPROVED": "Aprobado",
                "REJECTED": "Rechazado",
            }.get(st, st or "—")

        def _pill(st: str | None) -> str:
            st = (st or "").upper()
            return {
                "OPEN": "pending",
                "SUBMITTED": "submitted",
                "APPROVED": "approved",
                "REJECTED": "rejected",
                "": "none",
                None: "none",
            }.get(st, "other")

        counts = {"Pendiente": 0, "Enviado": 0, "Aprobado": 0, "Rechazado": 0, "Sin programación": 0}
        rows_out = []

        for st in stations:
            sid = int(st["id"])
            req = req_by_station.get(sid)
            if not req:
                counts["Sin programación"] += 1
                rows_out.append({
                    "station_id": sid,
                    "station_name": st.get("name") or f"Estación {sid}",
                    "station_code": st.get("code") or "",
                    "has_req": False,
                    "status_label": "Sin programación",
                    "status_pill": "none",
                    "status_key": "unplanned",
                    "requirement_id": None,
                    "title": None,
                    "template_name": None,
                    "assigned_user": None,
                    "due_date": None,
                    "submission": None,
                    "review_status": None,
                    "submitted_at": None,
                    "actions": [],
                })
                continue

            status_raw = (req.get("status") or "OPEN").upper()
            status_label = _label(status_raw)
            if status_label in counts:
                counts[status_label] += 1

            sub = sub_by_req.get(int(req["id"]))
            actions = [{"label": "Ver", "href": f"{admin_base}/reviews?requirement_id={int(req['id'])}"}]
            if sub:
                actions.append({"label": "Descargar PDF", "href": f"{admin_base}/submissions/{int(sub['id'])}/download"})
                if status_raw == "SUBMITTED":
                    actions.append({"label": "Revisar", "href": f"{admin_base}/reviews?requirement_id={int(req['id'])}"})

            rows_out.append({
                "station_id": sid,
                "station_name": st.get("name") or f"Estación {sid}",
                "station_code": st.get("code") or "",
                "has_req": True,
                "status_label": status_label,
                "status_pill": _pill(status_raw),
                "status_key": _pill(status_raw),
                "requirement_id": int(req["id"]),
                "title": req.get("title"),
                "template_name": req.get("template_name"),
                "assigned_user": req.get("assigned_user"),
                "due_date": req.get("due_date"),
                "submission": bool(sub),
                "review_status": sub.get("review_status") if sub else None,
                "submitted_at": sub.get("submitted_at") if sub else None,
                "actions": actions,
            })

        visible_rows = []
        q_norm = q.casefold()
        for row in rows_out:
            if status_filter != "all" and row.get("status_key") != status_filter:
                continue
            haystack = " ".join([
                str(row.get("station_name") or ""),
                str(row.get("station_code") or ""),
                str(row.get("title") or ""),
                str(row.get("template_name") or ""),
                str(row.get("assigned_user") or ""),
                str(row.get("status_label") or ""),
            ]).casefold()
            if q_norm and q_norm not in haystack:
                continue
            visible_rows.append(row)

        conn.close()

        if export_fmt == "csv":
            sio = io.StringIO()
            writer = csv.writer(sio)
            writer.writerow(["Estación", "Código", "Documento", "Plantilla", "Asignado", "Estatus", "Vence", "Enviado"])
            for row in visible_rows:
                writer.writerow([
                    row.get("station_name") or "",
                    row.get("station_code") or "",
                    row.get("title") or "",
                    row.get("template_name") or "",
                    row.get("assigned_user") or "",
                    row.get("status_label") or "",
                    row.get("due_date") or "",
                    row.get("submitted_at") or "",
                ])
            filename = f"{module_key}_tablero_{day}.csv"
            return app.response_class(
                sio.getvalue(),
                mimetype="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        filtered_counts = {
            "visible": len(visible_rows),
            "total": len(rows_out),
            "with_requirements": sum(1 for r in visible_rows if r.get("has_req")),
            "with_submission": sum(1 for r in visible_rows if r.get("submission")),
        }
        return render_template(
            f"{template_folder}/admin_board.html",
            **_base_context(
                day=day,
                rows=visible_rows,
                counts=counts,
                filtered_counts=filtered_counts,
                status_filter=status_filter,
                q=q,
                day_prev=(day_obj.date() - timedelta(days=1)).isoformat(),
                day_next=(day_obj.date() + timedelta(days=1)).isoformat(),
            ),
        )


    def staff_dashboard():
        me = _staff_allowed()
        if me.get("role") == "admin":
            return redirect(admin_base)
        return redirect(f"{staff_base}/records")

    def templates_page():
        _admin_required()
        conn = get_conn()
        templates = _template_choices(conn)
        stations = [dict(r) for r in conn.execute("SELECT id, name, code FROM stations WHERE brand=? ORDER BY name ASC", (_brand(),)).fetchall()]
        users = [dict(r) for r in conn.execute("SELECT id, username, role, station_id FROM users WHERE is_active=1 AND role!='admin' AND (primary_brand=? OR allowed_brands LIKE ?) ORDER BY username ASC", (_brand(), f"%{_brand()}%")).fetchall()]
        conn.close()
        return render_template(f"{template_folder}/templates.html", **_base_context(templates=templates, stations=stations, users=users))

    def template_upload():
        me = _admin_required()
        f = request.files.get("pdf")
        month_key = (request.form.get("month_key") or datetime.now(timezone.utc).strftime("%Y-%m")).strip()
        display_name = (request.form.get("name") or "").strip()
        create_daily = (request.form.get("create_daily") or "").strip() == "1"
        daily_station_id = (request.form.get("daily_station_id") or "").strip()
        daily_title = (request.form.get("daily_title") or "").strip()
        daily_due_date = (request.form.get("daily_due_date") or "").strip()

        if not f or not f.filename.lower().endswith(".pdf"):
            abort(400)
        filename = secure_filename(f.filename)
        relpath = _template_relpath(month_key, filename)
        storage.save_upload(f, relpath, content_type="application/pdf")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO doc_templates (brand, module, name, file_path, month_key, field_schema_json, is_published, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_brand(), module_key, display_name or Path(filename).stem, relpath, month_key, "[]", 1 if create_daily else 0, int(me["id"]), _now_iso()),
        )
        template_id = cur.lastrowid
        conn.commit()
        _ensure_template_previews(template_id, relpath)

        # Optional: create today's requirements per station (admin uploads daily template).
        if create_daily:
            open_date = date.today().isoformat()
            due_date = (daily_due_date or open_date)[:10]
            title_base = daily_title or f"{module_label} • {open_date}"
            station_ids = []
            if daily_station_id:
                try:
                    station_ids = [int(daily_station_id)]
                except Exception:
                    station_ids = []
            if not station_ids:
                station_ids = [int(r["id"]) for r in conn.execute(
                    "SELECT id FROM stations WHERE brand=? ORDER BY id ASC", (_brand(),)
                ).fetchall()]

            for sid in station_ids:
                existing = conn.execute(
                    "SELECT id, status FROM doc_requirements WHERE brand=? AND module=? AND station_id=? AND open_date=? ORDER BY id DESC LIMIT 1",
                    (_brand(), module_key, int(sid), open_date),
                ).fetchone()

                # If there is already a requirement for this station & day AND nobody has submitted yet, update it.
                if existing and not _attempt_info(conn, int(existing["id"])):
                    conn.execute(
                        "UPDATE doc_requirements SET template_id=?, title=?, due_date=?, status='OPEN', created_by=?, created_at=? "
                        "WHERE id=? AND brand=? AND module=?",
                        (int(template_id), f"{title_base} • {sid}", due_date, int(me["id"]), _now_iso(), int(existing["id"]), _brand(), module_key),
                    )
                else:
                    conn.execute(
                        "INSERT INTO doc_requirements (brand, module, template_id, title, open_date, due_date, station_id, assigned_user_id, status, created_by, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (_brand(), module_key, int(template_id), f"{title_base} • {sid}", open_date, due_date,
                         int(sid), None, "OPEN", int(me["id"]), _now_iso()),
                    )
            conn.commit()

        conn.close()
        return redirect(f"{admin_base}/templates")

    def edit_fields(template_id: int):
        _admin_required(); conn = get_conn(); tpl = _get_template(conn, template_id)
        if not tpl:
            conn.close(); abort(404)
        previews = _ensure_template_previews(template_id, tpl["file_path"])
        schema = _load_schema(tpl); conn.close()
        return render_template(f"{template_folder}/edit_fields.html", **_base_context(template_row=dict(tpl), previews=previews, schema_json=json.dumps(schema, ensure_ascii=False, indent=2), example_schema=_example_schema()))

    def save_fields(template_id: int):
        _admin_required(); conn = get_conn(); tpl = _get_template(conn, template_id)
        if not tpl:
            conn.close(); abort(404)
        schema = _parse_schema_input(request.form.get("schema_json") or "[]")
        conn.execute("UPDATE doc_templates SET field_schema_json=? WHERE id=? AND brand=? AND module=?", (_json_dumps(schema), template_id, _brand(), module_key))
        conn.commit(); conn.close(); return redirect(f"{admin_base}/templates/{template_id}/fields")

    def publish_template(template_id: int):
        _admin_required(); conn = get_conn(); conn.execute("UPDATE doc_templates SET is_published=1 WHERE id=? AND brand=? AND module=?", (template_id, _brand(), module_key)); conn.commit(); conn.close(); return redirect(f"{admin_base}/templates")

    def create_requirement():
        me = _admin_required()
        template_id = int(request.form.get("template_id") or 0)
        title = (request.form.get("title") or "").strip()
        open_date = (request.form.get("open_date") or "").strip()
        due_date = (request.form.get("due_date") or "").strip()
        station_id = (request.form.get("station_id") or "").strip()
        assigned_user_id = (request.form.get("assigned_user_id") or "").strip()
        if not template_id or not title or not open_date or not due_date:
            abort(400)
        conn = get_conn()
        conn.execute("""
            INSERT INTO doc_requirements (brand, module, template_id, title, open_date, due_date, station_id, assigned_user_id, status, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (_brand(), module_key, template_id, title, open_date, due_date, int(station_id) if station_id else None, int(assigned_user_id) if assigned_user_id else None, "OPEN", int(me["id"]), _now_iso()))
        conn.commit(); conn.close(); return redirect(f"{admin_base}/templates")

    def reviews():
        _admin_required(); requirement_id = (request.args.get("requirement_id") or "").strip(); conn = get_conn()
        sql = """
            SELECT ds.*, dr.title AS requirement_title, dt.name AS template_name,
                   u.username AS operator_name, s.name AS station_name
            FROM doc_submissions ds
            JOIN doc_requirements dr ON dr.id=ds.requirement_id AND dr.brand=ds.brand AND dr.module=ds.module
            JOIN doc_templates dt ON dt.id=dr.template_id AND dt.brand=dr.brand AND dt.module=dr.module
            LEFT JOIN users u ON u.id=ds.operator_id
            LEFT JOIN stations s ON s.id=dr.station_id
            WHERE ds.brand=? AND ds.module=?
        """
        params = [_brand(), module_key]
        if requirement_id:
            sql += " AND ds.requirement_id=?"; params.append(int(requirement_id))
        sql += " ORDER BY CASE WHEN ds.review_status='PENDING' THEN 0 ELSE 1 END, ds.submitted_at DESC"
        rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
        conn.close(); return render_template(f"{template_folder}/reviews.html", **_base_context(submissions=rows, requirement_id=requirement_id))

    def review_submission(submission_id: int):
        me = _admin_required(); status = (request.form.get("status") or "").strip().upper(); comment = (request.form.get("comment") or "").strip()
        if status not in {"CORRECT", "WRONG"}: abort(400)
        conn = get_conn(); sub = conn.execute("SELECT * FROM doc_submissions WHERE id=? AND brand=? AND module=?", (submission_id, _brand(), module_key)).fetchone()
        if not sub: conn.close(); abort(404)
        next_reopen = None
        conn.execute("UPDATE doc_submissions SET review_status=?, review_comment=?, reviewed_by=?, reviewed_at=? WHERE id=? AND brand=? AND module=?", (status, comment, int(me["id"]), _now_iso(), submission_id, _brand(), module_key))
        conn.execute("UPDATE doc_requirements SET status=? WHERE id=? AND brand=? AND module=?", ("APPROVED" if status == "CORRECT" else "REJECTED", int(sub["requirement_id"]), _brand(), module_key))

        conn.commit()

        # Notify operator about the review result.
        try:
            req_row = conn.execute(
                "SELECT title, station_id FROM doc_requirements WHERE id=? AND brand=? AND module=?",
                (int(sub["requirement_id"]), _brand(), module_key),
            ).fetchone()
            station_id = int(req_row["station_id"]) if req_row and req_row["station_id"] else None
            title = f"{module_label}: Documento {'aprobado' if status == 'CORRECT' else 'incorrecto'}"
            body = (req_row["title"] if req_row else "Documento")
            if comment:
                body += f" · {comment[:140]}"
            ctx.notify(int(sub["operator_id"]), station_id, title, body, staff_base, ntype="doc_review", brand=_brand())
            ctx.log_action(me, "doc_reviewed", entity=module_key, entity_id=str(sub["requirement_id"]), meta={"module": module_key, "status": status, "submission_id": submission_id})
            ctx.sign_entity(me, module_key, str(submission_id), f"review_{status.lower()}", {"requirement_id": int(sub["requirement_id"]), "comment": comment})

            # If WRONG and auto-reopen is scheduled, let the operator know the date.
            if status == "WRONG":
                try:
                    create_correction_task(
                        ctx, me, brand=_brand(), title=f"Corregir documento {body}", description=comment or body,
                        station_id=station_id, module=module_key, related_entity="doc_submission", related_entity_id=str(submission_id),
                        assigned_to=int(sub["operator_id"]) if sub.get("operator_id") else None, source_status="wrong", priority="high", due_days=3,
                    )
                except Exception:
                    pass
            if status == "WRONG" and next_reopen:
                try:
                    dt = datetime.fromisoformat(next_reopen)
                    body2 = f"Reintento disponible a partir de {dt.strftime('%Y-%m-%d')}"
                    ctx.notify(int(sub["operator_id"]), station_id, f"{module_label}: Reintento programado", body2, f"{staff_base}/capture/{int(sub['requirement_id'])}", ntype="doc_reopen_scheduled", brand=_brand())
                except Exception:
                    pass
        except Exception:
            pass

        conn.close()
        return redirect(f"{admin_base}/reviews")

    def unlock_requirement(requirement_id: int):
        # Policy: single submission only. Unlocks/retries disabled.
        _admin_required()
        abort(400, description="Desbloqueo deshabilitado: cada estación solo puede enviar una vez.")
    def capture(requirement_id: int):
        me = _staff_allowed()
        if me.get("role") == "admin":
            return redirect(f"{admin_base}/reviews?requirement_id={requirement_id}")
        return redirect(f"{staff_base}/records")

    def capture_submit(requirement_id: int):
        me = _staff_allowed()
        if me.get("role") == "admin":
            abort(403)
        abort(403, description="Las estaciones ya no capturan documentos en este módulo; solo pueden consultar y descargar los documentos enviados por administración.")
        conn = get_conn(); req = _get_requirement(conn, requirement_id)
        if not req or not _requirement_visible_to_user(me, req): conn.close(); abort(404)
        unlock = None; last = _attempt_info(conn, requirement_id)
        state, can_capture, helper = _compute_requirement_state(req, me, last_submission=last, unlock=unlock)
        if not can_capture:
            conn.close()
            return render_template(f"{template_folder}/capture.html", **_base_context(requirement=dict(req), schema=_load_schema(req), previews=_ensure_template_previews(req["template_id"], req["file_path"]), state=state, can_capture=False, helper=helper, error=helper, last_submission=dict(last) if last else None)), 400
        # Optional admin-configured lock date for document captures.
        try:
            lock_key = f"doc_capture_lock_date:{_brand()}"
            row0 = conn.execute("SELECT value FROM system_state WHERE key=?", (lock_key,)).fetchone()
            lock_date = (row0["value"] if row0 else "") or ""
            if lock_date and __import__("datetime").date.today() > __import__("datetime").date.fromisoformat(lock_date[:10]):
                conn.close()
                return render_template(f"{template_folder}/capture.html", **_base_context(requirement=dict(req), schema=_load_schema(req), previews=_ensure_template_previews(req["template_id"], req["file_path"]), state=state, can_capture=False, helper=f"Captura cerrada desde {lock_date[:10]}", error=f"Captura cerrada desde {lock_date[:10]}", last_submission=dict(last) if last else None)), 403
        except Exception:
            pass
        schema = _load_schema(req); values = {field["key"]: (request.form.get(field["key"]) or "").strip() for field in schema}
        attempt_no = 1
        station_id = int(req.get("station_id") or (me.get("station_id") or 0) or 0)
        out_rel = f"{module_key}_submissions/{_brand()}/req_{requirement_id}/station_{station_id}.pdf"
        _render_pdf(req["file_path"], schema, values, out_rel)
        conn.execute("INSERT INTO doc_submissions (brand, module, requirement_id, operator_id, attempt_no, submitted_at, pdf_path, field_values_json, review_status) VALUES (?,?,?,?,?,?,?,?,?)", (_brand(), module_key, requirement_id, int(me["id"]), attempt_no, _now_iso(), out_rel, _json_dumps(values), "PENDING"))
        sub_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        conn.execute("UPDATE doc_requirements SET status='SUBMITTED' WHERE id=? AND brand=? AND module=?", (requirement_id, _brand(), module_key))

        conn.commit()

        # Notify admins when a document is submitted (SASISOPA/SGM).
        try:
            station_id = req.get("station_id")
            st_name = None
            if station_id:
                r = conn.execute("SELECT name FROM stations WHERE id=?", (int(station_id),)).fetchone()
                st_name = (r["name"] if r else None)
            title = f"{module_label}: Documento enviado"
            body = f"{req.get('title') or 'Documento'}"
            if st_name:
                body += f" · {st_name}"
            url = f"{admin_base}/reviews?requirement_id={int(requirement_id)}"
            ctx.notify_admins(title, body, url, station_id=int(station_id) if station_id else None, exclude_user_id=int(me["id"]), ntype="doc_submission", brand=_brand())
            ctx.log_action(me, "doc_submitted", entity=module_key, entity_id=str(requirement_id), meta={"module": module_key, "station_id": station_id, "attempt": attempt_no})
            ctx.sign_entity(me, module_key, str(requirement_id), "submitted", {"submission_id": sub_id, "station_id": station_id})
        except Exception:
            pass

        conn.close()
        return redirect(staff_base)

    
    # ---------------- Saved records (admin fills + saves; staff views/downloads) ----------------
    def _get_record(conn, record_id: int):
        return conn.execute(
            "SELECT * FROM doc_records WHERE id=? AND brand=? AND module=?",
            (record_id, _brand(), module_key),
        ).fetchone()

    def _get_record_by_station(conn, station_id: int):
        return conn.execute(
            "SELECT * FROM doc_records WHERE brand=? AND module=? AND station_id=?",
            (_brand(), module_key, int(station_id)),
        ).fetchone()

    def _get_record_with_template(conn, record_id: int):
        return conn.execute(
            """
            SELECT r.*, dt.name AS template_name, dt.month_key, dt.file_path, dt.field_schema_json,
                   s.code AS station_code, s.name AS station_name
            FROM doc_records r
            JOIN doc_templates dt ON dt.id=r.template_id AND dt.brand=r.brand AND dt.module=r.module
            LEFT JOIN stations s ON s.id=r.station_id
            WHERE r.id=? AND r.brand=? AND r.module=?
            """,
            (int(record_id), _brand(), module_key),
        ).fetchone()

    def _record_values(record_row) -> dict:
        try:
            data = json.loads(record_row["field_values_json"] or "{}") or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _staff_editable_fields(schema: list[dict]) -> list[dict]:
        return [field for field in schema if bool(field.get("staff_editable"))]

    def _record_template_and_values(conn, row):
        tpl = _get_template(conn, int(row["template_id"])) if row else None
        schema = _load_schema(tpl) if tpl else []
        try:
            values = json.loads(row.get("field_values_json") or "{}") if row else {}
            if not isinstance(values, dict):
                values = {}
        except Exception:
            values = {}
        return tpl, schema, values

    def _staff_editable_fields(schema: list[dict]) -> list[dict]:
        return [f for f in schema if f.get("staff_editable")]

    def records_page():
        _admin_required()
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT r.*, dt.name AS template_name, dt.month_key, s.code AS station_code, s.name AS station_name
            FROM doc_records r
            JOIN doc_templates dt ON dt.id=r.template_id AND dt.brand=r.brand AND dt.module=r.module
            LEFT JOIN stations s ON s.id=r.station_id
            WHERE r.brand=? AND r.module=?
            ORDER BY r.updated_at DESC
            """,
            (_brand(), module_key),
        ).fetchall()
        conn.close()
        return render_template(f"{template_folder}/records.html", **_base_context(records=[dict(x) for x in rows]))

    def record_capture(template_id: int):
        """Admin captures field values for a template and saves it as the current record for a station."""
        me = _admin_required()
        station_id = (request.args.get("station_id") or "").strip()
        conn = get_conn()
        tpl = _get_template(conn, template_id)
        if not tpl:
            conn.close()
            abort(404)
        stations = conn.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY code, name", (_brand(),)).fetchall()
        schema = _load_schema(tpl)
        previews = _ensure_template_previews(int(template_id), tpl["file_path"])
        values = {}
        current = None
        if station_id:
            try:
                sid = int(station_id)
                current = _get_record_by_station(conn, sid)
                if current:
                    try:
                        loaded = json.loads(current.get("field_values_json") or "{}") or {}
                    except Exception:
                        loaded = {}
                    # Only prefill keys present in current schema (in case template changed)
                    schema_keys = {f.get("key") for f in schema}
                    values = {k: v for (k, v) in loaded.items() if k in schema_keys}
            except Exception:
                station_id = ""
        conn.close()
        return render_template(
            f"{template_folder}/record_capture.html",
            **_base_context(
                template_row=dict(tpl),
                previews=previews,
                schema=schema,
                stations=[dict(s) for s in stations],
                station_id=station_id,
                values=values,
                current_record=dict(current) if current else None,
            ),
        )

    def record_capture_save(template_id: int):
        me = _admin_required()
        station_id = (request.form.get("station_id") or "").strip()
        if not station_id:
            abort(400)
        sid = int(station_id)

        conn = get_conn()
        tpl = _get_template(conn, template_id)
        if not tpl:
            conn.close()
            abort(404)

        schema = _load_schema(tpl)
        values = {field["key"]: (request.form.get(field["key"]) or "").strip() for field in schema}
        out_rel = f"{module_key}_records/{_brand()}/station_{sid}/current.pdf"
        _render_pdf(tpl["file_path"], schema, values, out_rel)

        existing = _get_record_by_station(conn, sid)
        if existing:
            conn.execute(
                "UPDATE doc_records SET template_id=?, title=?, pdf_path=?, field_values_json=?, updated_by=?, updated_at=? WHERE id=? AND brand=? AND module=?",
                (int(template_id), tpl.get("name"), out_rel, _json_dumps(values), int(me["id"]), _now_iso(), int(existing["id"]), _brand(), module_key),
            )
            record_id = int(existing["id"])
        else:
            conn.execute(
                """
                INSERT INTO doc_records (brand, module, station_id, template_id, title, pdf_path, field_values_json, updated_by, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (_brand(), module_key, sid, int(template_id), tpl.get("name"), out_rel, _json_dumps(values), int(me["id"]), _now_iso()),
            )
            record_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        conn.commit()

        # Audit + notification (optional)
        try:
            ctx.log_action(me, "doc_record_saved", entity=module_key, entity_id=str(record_id), meta={"module": module_key, "station_id": sid, "template_id": int(template_id)})
        except Exception:
            pass

        conn.close()
        return redirect(f"{admin_base}/records")

    def record_download(record_id: int):
        _admin_required()
        conn = get_conn()
        row = _get_record_with_template(conn, record_id)
        conn.close()
        if not row:
            abort(404)
        return storage.send(row["pdf_path"], as_attachment=True)

    def staff_records_page():
        me = _staff_allowed()
        conn = get_conn()
        station_scope = []
        if me.get("role") != "admin":
            station_scope = sorted(int(x) for x in ctx.station_scope_ids(me))
            if not station_scope:
                conn.close()
                return render_template(f"{template_folder}/staff_records.html", **_base_context(records=[], error="Tu usuario no tiene estación asignada.")), 400
        sql = """
            SELECT r.*, dt.name AS template_name, dt.month_key, dt.field_schema_json,
                   s.code AS station_code, s.name AS station_name
            FROM doc_records r
            JOIN doc_templates dt ON dt.id=r.template_id AND dt.brand=r.brand AND dt.module=r.module
            LEFT JOIN stations s ON s.id=r.station_id
            WHERE r.brand=? AND r.module=?
        """
        params = [_brand(), module_key]
        if station_scope:
            qmarks = ",".join(["?"] * len(station_scope))
            sql += f" AND r.station_id IN ({qmarks})"
            params.extend(station_scope)
        sql += " ORDER BY r.updated_at DESC"
        rows = [dict(x) for x in conn.execute(sql, tuple(params)).fetchall()]
        conn.close()
        for row in rows:
            schema = _load_schema(row)
            editable_fields = _staff_editable_fields(schema)
            row["has_staff_editable"] = bool(editable_fields)
            row["staff_editable_count"] = len(editable_fields)
        return render_template(f"{template_folder}/staff_records.html", **_base_context(records=rows))

    def staff_record_download(record_id: int):
        me = _staff_allowed()
        conn = get_conn()
        row = _get_record_with_template(conn, record_id)
        if not row:
            conn.close()
            abort(404)
        if me.get("role") != "admin":
            station_id = int(row.get("station_id") or 0) if row.get("station_id") else 0
            if not station_id or not ctx.can_access_station(me, station_id):
                conn.close()
                abort(403)
        conn.close()
        return storage.send(row["pdf_path"], as_attachment=True)


    def staff_record_edit(record_id: int):
        me = _staff_allowed()
        conn = get_conn()
        row = _get_record_with_template(conn, record_id)
        if not row:
            conn.close()
            abort(404)
        station_id = int(row.get("station_id") or 0) if row.get("station_id") else 0
        if me.get("role") != "admin" and (not station_id or not ctx.can_access_station(me, station_id)):
            conn.close()
            abort(403)
        tpl, schema, values = _record_template_and_values(conn, row)
        editable = _staff_editable_fields(schema)
        if not editable:
            conn.close()
            abort(403)
        conn.close()
        return render_template(f"{template_folder}/staff_record_edit.html", **_base_context(record=dict(row), template_row=dict(tpl) if tpl else None, schema=editable, values=values))

    def staff_record_edit_save(record_id: int):
        me = _staff_allowed()
        conn = get_conn()
        row = _get_record_with_template(conn, record_id)
        if not row:
            conn.close()
            abort(404)
        station_id = int(row.get("station_id") or 0) if row.get("station_id") else 0
        if me.get("role") != "admin" and (not station_id or not ctx.can_access_station(me, station_id)):
            conn.close()
            abort(403)
        tpl, schema, values = _record_template_and_values(conn, row)
        editable = _staff_editable_fields(schema)
        if not editable:
            conn.close()
            abort(403)
        editable_keys = {f.get("key") for f in editable}
        for field in editable:
            values[field["key"]] = (request.form.get(field["key"]) or "").strip()
        out_rel = row.get("pdf_path") or f"{module_key}_records/{_brand()}/station_{station_id}/current.pdf"
        _render_pdf(tpl["file_path"], schema, values, out_rel)
        conn.execute(
            "UPDATE doc_records SET field_values_json=?, pdf_path=?, updated_by=?, updated_at=? WHERE id=? AND brand=? AND module=?",
            (_json_dumps(values), out_rel, int(me["id"]), _now_iso(), int(record_id), _brand(), module_key),
        )
        conn.commit()
        try:
            ctx.log_action(me, "doc_record_staff_edit", entity=module_key, entity_id=str(record_id), meta={"module": module_key, "station_id": station_id, "editable_keys": sorted([k for k in editable_keys if k])})
        except Exception:
            pass
        conn.close()
        return redirect(f"{staff_base}/records")

    def download(submission_id: int):
        _admin_required(); conn = get_conn(); row = conn.execute("SELECT pdf_path FROM doc_submissions WHERE id=? AND brand=? AND module=?", (submission_id, _brand(), module_key)).fetchone(); conn.close()
        if not row: abort(404)
        return storage.send(row["pdf_path"], as_attachment=True)

    def health():
        me = _staff_allowed(); conn = get_conn()
        templates = conn.execute("SELECT COUNT(*) AS c FROM doc_templates WHERE brand=? AND module=?", (_brand(), module_key)).fetchone()["c"]
        requirements = conn.execute("SELECT COUNT(*) AS c FROM doc_requirements WHERE brand=? AND module=?", (_brand(), module_key)).fetchone()["c"]
        submissions = conn.execute("SELECT COUNT(*) AS c FROM doc_submissions WHERE brand=? AND module=?", (_brand(), module_key)).fetchone()["c"]
        conn.close(); return jsonify({"ok": True, "brand": _brand(), "module": module_key, "templates": templates, "requirements": requirements, "submissions": submissions, "role": me.get("role")})

    _route(admin_base, f"{module_key}_docs_admin_dashboard", admin_dashboard)
    _route(f"{admin_base}/board", f"{module_key}_docs_admin_board", admin_board)
    _route(staff_base, f"{module_key}_docs_staff_dashboard", staff_dashboard)
    _route(f"{admin_base}/templates", f"{module_key}_docs_templates_page", templates_page)
    _route(f"{admin_base}/templates/upload", f"{module_key}_docs_template_upload", template_upload, methods=("POST",))
    _route(f"{admin_base}/templates/<int:template_id>/fields", f"{module_key}_docs_edit_fields", edit_fields)
    _route(f"{admin_base}/templates/<int:template_id>/fields", f"{module_key}_docs_save_fields", save_fields, methods=("POST",))
    _route(f"{admin_base}/templates/<int:template_id>/publish", f"{module_key}_docs_publish_template", publish_template, methods=("POST",))
    _route(f"{admin_base}/requirements", f"{module_key}_docs_create_requirement", create_requirement, methods=("POST",))
    _route(f"{admin_base}/reviews", f"{module_key}_docs_reviews", reviews)
    _route(f"{admin_base}/submissions/<int:submission_id>/review", f"{module_key}_docs_review_submission", review_submission, methods=("POST",))
    _route(f"{admin_base}/requirements/<int:requirement_id>/unlock", f"{module_key}_docs_unlock_requirement", unlock_requirement, methods=("POST",))
    _route(f"{staff_base}/capture/<int:requirement_id>", f"{module_key}_docs_capture", capture)
    _route(f"{staff_base}/capture/<int:requirement_id>", f"{module_key}_docs_capture_submit", capture_submit, methods=("POST",))
    _route(f"{admin_base}/submissions/<int:submission_id>/download", f"{module_key}_docs_download", download)

    _route(f"{admin_base}/records", f"{module_key}_docs_records_page", records_page)
    _route(f"{admin_base}/records/<int:record_id>/download", f"{module_key}_docs_record_download", record_download)
    _route(f"{admin_base}/templates/<int:template_id>/record", f"{module_key}_docs_record_capture", record_capture)
    _route(f"{admin_base}/templates/<int:template_id>/record", f"{module_key}_docs_record_capture_save", record_capture_save, methods=("POST",))

    _route(f"{staff_base}/records", f"{module_key}_docs_staff_records", staff_records_page)
    _route(f"{staff_base}/records/<int:record_id>/download", f"{module_key}_docs_staff_record_download", staff_record_download)
    _route(f"{staff_base}/records/<int:record_id>/edit", f"{module_key}_docs_staff_record_edit", staff_record_edit)
    _route(f"{staff_base}/records/<int:record_id>/edit", f"{module_key}_docs_staff_record_edit_save", staff_record_edit_save, methods=("POST",))

    _route(f"/api/{route_segment}/docs/health", f"{module_key}_docs_health", health)
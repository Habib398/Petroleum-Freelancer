from __future__ import annotations

from flask import jsonify, request, render_template
import datetime
from db import get_conn
from services.brand import get_brand

# Central list of calibration items (same for all stations)
CAL_ITEMS = [
    {"key": "dispensarios", "title": "Dispensarios", "hint": "Certificados / Evidencias de calibración de dispensarios."},
    {"key": "tanques", "title": "Tanques", "hint": "Tablas volumétricas / pruebas y calibración de tanques."},
    {"key": "bomba_sumergible", "title": "Bomba sumergible", "hint": "Revisión y calibración, checklist y evidencia."},
    {"key": "sensores", "title": "Sensores / sondas", "hint": "Sensores, varillas, medición y evidencias."},
    {"key": "flujometros", "title": "Flujómetros", "hint": "Certificados y verificación metrológica."},
    {"key": "mangueras", "title": "Mangueras / pistolas", "hint": "Inspección y mantenimiento/cambio con evidencia."},
]

def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/admin/calibraciones")
    @login_required
    @role_required("admin")
    def admin_calibraciones_v2():
        # UI only; data via API
        return render_template("admin/calibraciones_v2.html")

    @app.get("/api/calibraciones/items")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_calibraciones_items():
        return jsonify({"ok": True, "items": CAL_ITEMS})

    @app.get("/api/calibraciones/summary")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_calibraciones_summary():
        brand = get_brand()
        me = ctx.get_me() or {}

        conn = get_conn(); cur = conn.cursor()
        # station scope
        if me.get("role") == "admin":
            cur.execute("SELECT id, code, name FROM stations WHERE brand=? ORDER BY name", (brand,))
            stations = [dict(r) for r in cur.fetchall()]
        else:
            scope = list(ctx.station_scope_ids(me))
            if scope:
                in_clause = ",".join(["?"] * len(scope))
                cur.execute(f"SELECT id, code, name FROM stations WHERE brand=? AND id IN ({in_clause}) ORDER BY name", [brand, *scope])
                stations = [dict(r) for r in cur.fetchall()]
            else:
                stations = []

        # For each station/item check if there's a current document
        # Use EXISTS for speed (N stations x items is OK for small N)
        for s in stations:
            done = 0
            for it in CAL_ITEMS:
                cur.execute(
                    "SELECT 1 FROM documents WHERE brand=? AND station_id=? AND module='calibraciones' AND section=? AND is_current=1 LIMIT 1",
                    (brand, s["id"], it["key"]),
                )
                if cur.fetchone():
                    done += 1
            total = len(CAL_ITEMS)
            s["realizadas"] = done
            s["pendientes"] = max(total - done, 0)
            # placeholders (you can expand later with due dates)
            s["programadas"] = 0
            s["fuera_plazo"] = 0
            s["pct"] = int(round((done / total) * 100)) if total else 0

        conn.close()
        return jsonify({"ok": True, "brand": brand, "stations": stations, "total_items": len(CAL_ITEMS)})

    @app.get("/api/calibraciones/station/<int:station_id>")
    @login_required
    @role_required("admin", "jefe_estacion", "operador", "auditor", "contador")
    def api_calibraciones_station(station_id: int):
        brand = get_brand()
        me = ctx.get_me() or {}

        if me.get("role") != "admin":
            scope = set(ctx.station_scope_ids(me))
            if station_id not in scope:
                return jsonify({"ok": False, "error": "forbidden"}), 403

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE id=? AND brand=?", (station_id, brand))
        st = cur.fetchone()
        if not st:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404
        station = dict(st)

        items = []
        for it in CAL_ITEMS:
            # current doc
            cur.execute(
                """
                SELECT id, title, file_path, created_at, version_no
                FROM documents
                WHERE brand=? AND station_id=? AND module='calibraciones' AND section=? AND is_current=1
                ORDER BY id DESC LIMIT 1
                """,
                (brand, station_id, it["key"]),
            )
            doc = cur.fetchone()
            if doc:
                d = dict(doc)
                d["url"] = "/uploads/" + d["file_path"].replace('\\', '/')
                it_state = "done"
            else:
                d = None
                it_state = "pending"

            # history count
            cur.execute(
                "SELECT COUNT(1) FROM documents WHERE brand=? AND station_id=? AND module='calibraciones' AND section=?",
                (brand, station_id, it["key"]),
            )
            hist = int(cur.fetchone()[0] or 0)

            items.append({**it, "state": it_state, "current": d, "history_count": hist})

        conn.close()
        return jsonify({"ok": True, "station": station, "items": items})

    # ---------------- Calibración de Tanques (admin-only por ahora) ----------------

    @app.get("/api/calibraciones/tanks")
    @login_required
    @role_required("admin")
    def api_cal_tanks_list():
        """Lista tanques por estación para Calibraciones (solo admin)."""
        brand = get_brand()
        station_id = request.args.get("station_id")
        if not station_id:
            return jsonify({"ok": False, "error": "missing_station_id"}), 400
        try:
            sid = int(station_id)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_station_id"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT 1 FROM stations WHERE id=? AND brand=?", (sid, brand))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "station_not_found"}), 404

        cur.execute(
            """
            SELECT
              id, name,
              pdf_path, pdf_uploaded_at, pdf_uploaded_by,
              sonda_pdf_path, sonda_pdf_uploaded_at, sonda_pdf_uploaded_by,
              temp_pdf_path, temp_pdf_uploaded_at, temp_pdf_uploaded_by,
              created_at
            FROM cal_tanks
            WHERE brand=? AND station_id=?
            ORDER BY id ASC
            """,
            (brand, sid),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "items": rows})

    @app.post("/api/calibraciones/tanks")
    @login_required
    @role_required("admin")
    def api_cal_tanks_create():
        """Crea un tanque (sin PDF) para una estación."""
        brand = get_brand()
        me = ctx.get_me() or {}

        data = request.get_json(silent=True) or {}
        station_id = data.get("station_id")
        name = (data.get("name") or "").strip()
        if not station_id:
            return jsonify({"ok": False, "error": "missing_station_id"}), 400
        try:
            sid = int(station_id)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_station_id"}), 400
        if not name:
            return jsonify({"ok": False, "error": "missing_name", "message": "El nombre del tanque es obligatorio"}), 400
        if len(name) > 80:
            return jsonify({"ok": False, "error": "name_too_long"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT 1 FROM stations WHERE id=? AND brand=?", (sid, brand))
        if not cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "station_not_found"}), 404

        # Avoid duplicate tank names per station (case-insensitive best-effort)
        cur.execute(
            "SELECT 1 FROM cal_tanks WHERE brand=? AND station_id=? AND lower(name)=lower(?) LIMIT 1",
            (brand, sid, name),
        )
        if cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "error": "duplicate", "message": "Ya existe un tanque con ese nombre en esta estación"}), 409

        cur.execute(
            "INSERT INTO cal_tanks(brand, station_id, name, created_by) VALUES(?,?,?,?)",
            (brand, sid, name, me.get("id")),
        )
        tank_id = cur.lastrowid
        conn.commit(); conn.close()
        ctx.log_action(me, "create_cal_tank", "cal_tanks", str(tank_id), {"station_id": sid, "name": name})
        return jsonify({"ok": True, "id": tank_id})

    @app.post("/api/calibraciones/tanks/<int:tank_id>/upload")
    @login_required
    @role_required("admin")
    def api_cal_tanks_upload(tank_id: int):
        """Sube/reemplaza el PDF de un tanque.

        kind: calibracion | sonda | temperatura
        """
        brand = get_brand()
        me = ctx.get_me() or {}
        kind = (request.args.get("kind") or "calibracion").strip().lower()
        if kind in {"cal", "calibracion", "tank", "tanque"}:
            kind = "calibracion"
        elif kind in {"sonda", "probe"}:
            kind = "sonda"
        elif kind in {"temp", "temperatura"}:
            kind = "temperatura"
        else:
            return jsonify({"ok": False, "error": "invalid_kind"}), 400
        f = request.files.get("file")
        if not f or not (f.filename or "").strip():
            return jsonify({"ok": False, "error": "missing_file"}), 400

        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, station_id FROM cal_tanks WHERE id=? AND brand=?", (tank_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "not_found"}), 404
        station_id = int(row["station_id"])

        relpath = ctx.save_upload_checked(
            f,
            f"docs/calibraciones/tanques/st{station_id}/tank{tank_id}/{kind}",
            allowed_ext={".pdf"},
            allowed_magic={"pdf"},
            limit_mb=20,
        )
        if not relpath:
            conn.close()
            return jsonify({"ok": False, "error": "save_failed"}), 400

        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if kind == "calibracion":
            cur.execute(
                "UPDATE cal_tanks SET pdf_path=?, pdf_uploaded_at=?, pdf_uploaded_by=? WHERE id=? AND brand=?",
                (relpath, now, me.get("id"), tank_id, brand),
            )
        elif kind == "sonda":
            cur.execute(
                "UPDATE cal_tanks SET sonda_pdf_path=?, sonda_pdf_uploaded_at=?, sonda_pdf_uploaded_by=? WHERE id=? AND brand=?",
                (relpath, now, me.get("id"), tank_id, brand),
            )
        else:  # temperatura
            cur.execute(
                "UPDATE cal_tanks SET temp_pdf_path=?, temp_pdf_uploaded_at=?, temp_pdf_uploaded_by=? WHERE id=? AND brand=?",
                (relpath, now, me.get("id"), tank_id, brand),
            )
        conn.commit(); conn.close()
        ctx.log_action(me, "upload_cal_tank_pdf", "cal_tanks", str(tank_id), {"station_id": station_id, "kind": kind, "file": relpath})
        return jsonify({"ok": True, "kind": kind, "pdf_path": relpath, "uploaded_at": now})

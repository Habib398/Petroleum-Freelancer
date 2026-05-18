"""Bloque F · Expedientes (cap. 4 de la propuesta)

Verifica el flujo completo de Expediente Documental para el área de
``normativas`` (petroleum). La propuesta también menciona ``tramites``
(consulting), pero esa rama está deshabilitada por feature-flag en
``modules/compliance/tramites_normativas.py`` (responde 410
``tramites_disabled``) — el bloque incluye un par de checks para confirmar
que esa puerta cerrada sigue cerrada y nadie la abre por accidente.

Áreas cubiertas:

* ``GET /api/expedientes/meta`` devuelve plantillas seed (6 baseline),
  estaciones y el catálogo de estatus.
* ``GET /api/expedientes/items`` arma la lista combinando plantillas con
  registros existentes. Sin registros, todas las plantillas obligatorias
  aparecen como ``faltante`` y suman a ``required_missing``.
* ``POST /api/expedientes/records`` crea un registro nuevo y, al
  reutilizar ``template_id`` para la misma estación, hace upsert.
* ``POST /api/expedientes/templates`` está restringido a admin.
* ``POST /api/expedientes/<id>/file`` sube archivo, incrementa
  ``version_count``, registra fila en ``expediente_versions`` y
  promueve ``faltante`` → ``vigente`` automáticamente.
* ``GET /api/expedientes/<id>/versions`` devuelve historial en orden
  descendente.
* Auto-cálculo de ``expiry_date`` cuando se pasa ``issue_date`` + plantilla
  con ``default_validity_days``.
* ``sync_document_deadlines`` corre después del upsert y produce una fila
  en ``document_deadlines`` con ``source_table='expediente_records'``.
* Jefe de estación sólo puede leer/escribir su(s) estación(es).
* La rama ``tramites`` responde 410 en todas las rutas relevantes.
* Gap documentado: NO existe endpoint de export ZIP del expediente
  (``L13`` en el documento PLAN_DE_PRUEBAS marca esto como NO PROBAR,
  pero confirmamos como 404 para que regrese aquí si alguien lo agrega).
"""

from __future__ import annotations

import datetime as _dt
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    db_get,
    db_row_count,
    login,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


def days_from_today(n: int) -> str:
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def set_session_brand(env, brand: str) -> None:
    with env.client.session_transaction() as s:
        s["brand"] = brand


def insert_extra_station(brand: str, code: str, name: str, group_name: str | None) -> int:
    """Inserta una estación adicional para probar scoping cruzado."""
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name) VALUES (?,?,?,?,?)",
        (brand, name, code, code, group_name),
    )
    sid = int(cur.lastrowid)
    conn.commit(); conn.close()
    return sid


def fake_pdf_bytes() -> bytes:
    """Mínimo PDF válido para validar la subida (file-magic basta con el header)."""
    return b"%PDF-1.4\n% test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def main() -> int:
    rep = TestReporter("Bloque F · Expedientes (Normativas)")
    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_pet = baseline.station_petroleum_id

        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")

        # ====== 1. GET /api/expedientes/meta?area=normativas ====================
        rep.section("GET /api/expedientes/meta?area=normativas devuelve seed completo")
        resp = env.client.get("/api/expedientes/meta?area=normativas")
        rep.check("meta?area=normativas → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        meta = resp.get_json() or {}
        rep.check("meta.ok=True y brand=petroleum",
                  meta.get("ok") is True and meta.get("brand") == "petroleum")
        rep.check("meta.area_label='Normativas'",
                  meta.get("area_label") == "Normativas",
                  f"got {meta.get('area_label')!r}")
        templates = meta.get("templates") or []
        rep.check("meta.templates trae 6 plantillas seed petroleum/normativas",
                  len(templates) == 6,
                  f"got {len(templates)}")
        codes = {(t.get("code") or "") for t in templates}
        rep.check("templates incluyen 'permiso_cre' y 'poliza_seguro'",
                  {"permiso_cre", "poliza_seguro"}.issubset(codes),
                  f"codes={codes}")
        stations = meta.get("stations") or []
        rep.check("meta.stations incluye al menos la estación petroleum baseline",
                  any(s.get("id") == sid_pet for s in stations),
                  f"stations={[s.get('id') for s in stations]}")
        statuses = meta.get("statuses") or []
        rep.check("meta.statuses incluye los 6 estados estándar",
                  {"faltante", "vigente", "proximo_a_vencer",
                   "vencido", "en_revision", "no_aplica"}.issubset(set(statuses)),
                  f"statuses={statuses}")

        # ====== 2. tramites está deshabilitado ==================================
        rep.section("Rama 'tramites' está deshabilitada (410)")
        resp = env.client.get("/api/expedientes/meta?area=tramites")
        rep.check("meta?area=tramites → 410",
                  resp.status_code == 410, f"got {resp.status_code}")
        body = resp.get_json() or {}
        rep.check("meta tramites devuelve error='tramites_disabled'",
                  body.get("error") == "tramites_disabled")
        resp = env.client.get(f"/api/expedientes/items?area=tramites&station_id={sid_pet}")
        rep.check("items?area=tramites → 410",
                  resp.status_code == 410, f"got {resp.status_code}")
        resp = env.client.post("/api/expedientes/records",
                                json={"area": "tramites", "station_id": sid_pet,
                                      "template_id": 1, "title": "X"})
        rep.check("records POST area=tramites → 410",
                  resp.status_code == 410, f"got {resp.status_code}")

        # ====== 3. items sin records: todos los obligatorios son 'faltante' =====
        rep.section("items inicial: plantillas sin registro → 'faltante' y required_missing")
        resp = env.client.get(f"/api/expedientes/items?area=normativas&station_id={sid_pet}")
        rep.check("items → 200", resp.status_code == 200)
        body = resp.get_json() or {}
        items = body.get("items") or []
        summary = body.get("summary") or {}
        rep.check("items trae 6 entries (una por plantilla seed)",
                  len(items) == 6, f"got {len(items)}")
        rep.check("todos los items aparecen como 'faltante' (missing=1)",
                  all(it.get("missing") == 1 for it in items),
                  f"got missing={[it.get('missing') for it in items]}")
        rep.check("summary.required_missing == 5 (5 obligatorios + 1 no obligatorio)",
                  summary.get("required_missing") == 5,
                  f"summary={summary}")
        rep.check("scope_label menciona el código de la estación",
                  baseline.station_petroleum_code in (body.get("scope_label") or ""),
                  f"got {body.get('scope_label')!r}")

        # ====== 4. items sin station_id → 400 station_required =================
        rep.section("Validación de scope: items?area=normativas SIN station_id → 400")
        resp = env.client.get("/api/expedientes/items?area=normativas")
        rep.check("items sin station_id → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='station_required'",
                  (resp.get_json() or {}).get("error") == "station_required")

        # ====== 5. POST records: crear registro nuevo ==========================
        rep.section("POST records crea registro nuevo")
        tpl_permiso = next((t for t in templates if t.get("code") == "permiso_cre"), None)
        rep.check("plantilla 'permiso_cre' encontrada en seed",
                  tpl_permiso is not None)
        tpl_permiso_id = (tpl_permiso or {}).get("id")
        issue = days_from_today(-30)
        resp = env.client.post("/api/expedientes/records", json={
            "area": "normativas",
            "station_id": sid_pet,
            "template_id": tpl_permiso_id,
            "status": "vigente",
            "issue_date": issue,
            "notes": "Carga inicial",
        })
        rep.check("POST records → 200",
                  resp.status_code == 200, f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        rep.check("body.ok=True y body.id presente",
                  body.get("ok") is True and isinstance(body.get("id"), int))
        rec_id = int(body.get("id"))

        # ====== 6. expiry_date auto-calculada (issue_date + 365d) ==============
        rep.section("Auto-cálculo de expiry_date a partir de issue_date + default_validity_days")
        rec_db = db_get("expediente_records", "id=?", (rec_id,))
        expected_expiry = (_dt.date.fromisoformat(issue) + _dt.timedelta(days=365)).isoformat()
        rep.check("expiry_date == issue_date + 365 días (validez por plantilla)",
                  (rec_db or {}).get("expiry_date") == expected_expiry,
                  f"got expiry_date={rec_db.get('expiry_date') if rec_db else None}, expected={expected_expiry}")
        rep.check("status='vigente' persistido",
                  (rec_db or {}).get("status") == "vigente")
        rep.check("version_count inicial = 0",
                  (rec_db or {}).get("version_count") == 0)

        # ====== 7. items refleja el registro creado ============================
        rep.section("items refleja el registro creado (missing=0, computed_status)")
        resp = env.client.get(f"/api/expedientes/items?area=normativas&station_id={sid_pet}")
        items = (resp.get_json() or {}).get("items") or []
        permiso_item = next((it for it in items
                             if it.get("template_id") == tpl_permiso_id), None)
        rep.check("item de 'permiso_cre' encontrado",
                  permiso_item is not None)
        rep.check("permiso_cre.missing == 0",
                  (permiso_item or {}).get("missing") == 0)
        rep.check("permiso_cre.computed_status == 'vigente' (expiry > 30d)",
                  (permiso_item or {}).get("computed_status") == "vigente",
                  f"got {permiso_item.get('computed_status') if permiso_item else None}")
        summary2 = (resp.get_json() or {}).get("summary") or {}
        rep.check("summary.required_missing bajó a 4",
                  summary2.get("required_missing") == 4,
                  f"summary={summary2}")

        # ====== 8. POST records re-aplicado al mismo template_id hace upsert ===
        rep.section("Re-POST con mismo (station_id, template_id) hace UPDATE no INSERT")
        prev_count = db_row_count("expediente_records",
                                   "station_id=? AND template_id=?",
                                   (sid_pet, tpl_permiso_id))
        resp = env.client.post("/api/expedientes/records", json={
            "area": "normativas",
            "station_id": sid_pet,
            "template_id": tpl_permiso_id,
            "status": "en_revision",
            "issue_date": issue,
            "notes": "Cambio a revisión",
        })
        rep.check("re-POST → 200", resp.status_code == 200)
        new_count = db_row_count("expediente_records",
                                  "station_id=? AND template_id=?",
                                  (sid_pet, tpl_permiso_id))
        rep.check("count NO cambió (upsert, no insert)",
                  new_count == prev_count, f"prev={prev_count}, new={new_count}")
        rec_db = db_get("expediente_records", "id=?", (rec_id,))
        rep.check("status actualizado a 'en_revision'",
                  (rec_db or {}).get("status") == "en_revision")
        rep.check("notes actualizado",
                  (rec_db or {}).get("notes") == "Cambio a revisión")

        # ====== 9. POST templates como admin ====================================
        rep.section("POST /api/expedientes/templates (solo admin)")
        resp = env.client.post("/api/expedientes/templates", json={
            "area": "normativas",
            "title": "Plantilla extra de prueba",
            "code": "extra_test",
            "description": "Plantilla creada por el test",
            "is_required": 1,
            "default_validity_days": 180,
            "sort_order": 999,
        })
        rep.check("admin POST templates → 200",
                  resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        rep.check("body.id devuelto",
                  isinstance(body.get("id"), int))
        new_tpl_id = body.get("id")
        tpl_db = db_get("expediente_templates", "id=?", (new_tpl_id,))
        rep.check("plantilla persistida en BD con brand=petroleum, area=normativas",
                  (tpl_db or {}).get("brand") == "petroleum"
                  and (tpl_db or {}).get("area") == "normativas")

        # ====== 10. POST templates rechazado para no-admin =====================
        rep.section("Jefe NO puede crear plantillas (solo admin)")
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")
        resp = env.client.post("/api/expedientes/templates", json={
            "area": "normativas", "title": "X",
        })
        rep.check("jefe → POST templates → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 11. Upload de archivo (versión 1) ==============================
        rep.section("POST /<id>/file sube archivo, bumpea version_count, promueve a 'vigente'")
        # Volvemos a admin para subir
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        # Buscar el item de bitacora_operacion (validez 30d) — está 'faltante'
        tpl_bita = next((t for t in templates if t.get("code") == "bitacora_operacion"), None)
        rep.check("plantilla 'bitacora_operacion' encontrada",
                  tpl_bita is not None)
        # Crear primero el registro en 'faltante'
        resp = env.client.post("/api/expedientes/records", json={
            "area": "normativas",
            "station_id": sid_pet,
            "template_id": (tpl_bita or {}).get("id"),
            "status": "faltante",
        })
        rep.check("registro bitácora creado en 'faltante'",
                  resp.status_code == 200)
        bita_id = int((resp.get_json() or {}).get("id"))
        # Subir archivo
        data = {
            "file": (io.BytesIO(fake_pdf_bytes()), "bitacora_oct.pdf"),
            "notes": "primera carga",
        }
        resp = env.client.post(
            f"/api/expedientes/{bita_id}/file",
            data=data, content_type="multipart/form-data",
        )
        rep.check("upload v1 → 200",
                  resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        rep.check("version_no == 1 en respuesta",
                  body.get("version_no") == 1, f"got {body.get('version_no')}")
        rep.check("file_url comienza con /uploads/",
                  (body.get("file_url") or "").startswith("/uploads/"))
        bita_db = db_get("expediente_records", "id=?", (bita_id,))
        rep.check("status saltó de 'faltante' a 'vigente' al subir el archivo",
                  (bita_db or {}).get("status") == "vigente",
                  f"got status={bita_db.get('status') if bita_db else None}")
        rep.check("version_count == 1",
                  (bita_db or {}).get("version_count") == 1)
        rep.check("current_file_path no es None",
                  bool((bita_db or {}).get("current_file_path")))

        # ====== 12. Upload v2 — segunda versión, version_count = 2 =============
        rep.section("Segundo upload bumpea version_count y crea fila en expediente_versions")
        data = {
            "file": (io.BytesIO(fake_pdf_bytes() + b"v2"), "bitacora_nov.pdf"),
            "notes": "segunda carga",
        }
        resp = env.client.post(
            f"/api/expedientes/{bita_id}/file",
            data=data, content_type="multipart/form-data",
        )
        rep.check("upload v2 → 200", resp.status_code == 200)
        rep.check("version_no == 2",
                  (resp.get_json() or {}).get("version_no") == 2)
        v_count = db_row_count("expediente_versions", "record_id=?", (bita_id,))
        rep.check("expediente_versions tiene 2 filas para este record",
                  v_count == 2, f"got {v_count}")

        # ====== 13. GET versions devuelve historial descendente ================
        rep.section("GET /<id>/versions ordenado descendente")
        resp = env.client.get(f"/api/expedientes/{bita_id}/versions")
        rep.check("versions → 200", resp.status_code == 200)
        body = resp.get_json() or {}
        vers = body.get("items") or []
        rep.check("versions tiene 2 entries", len(vers) == 2,
                  f"got {len(vers)}")
        if len(vers) >= 2:
            rep.check("orden DESC: vers[0].version_no > vers[1].version_no",
                      vers[0].get("version_no") > vers[1].get("version_no"),
                      f"got {vers[0].get('version_no')} vs {vers[1].get('version_no')}")
            rep.check("primer item incluye notes 'segunda carga'",
                      vers[0].get("notes") == "segunda carga")
            rep.check("uploaded_by_name == 'admin'",
                      vers[0].get("uploaded_by_name") == "admin",
                      f"got {vers[0].get('uploaded_by_name')!r}")

        # ====== 14. Upload de archivo con extensión NO permitida → 400 =========
        rep.section("Upload con extensión inválida es rechazado")
        data = {
            "file": (io.BytesIO(b"#!/bin/sh\necho hi"), "evil.sh"),
        }
        resp = env.client.post(
            f"/api/expedientes/{bita_id}/file",
            data=data, content_type="multipart/form-data",
        )
        rep.check("upload .sh → 4xx o 5xx (rechazado de algún modo)",
                  resp.status_code >= 400, f"got {resp.status_code}")
        # version_count no se debe haber tocado
        bita_db = db_get("expediente_records", "id=?", (bita_id,))
        rep.check("version_count sigue en 2 después del rechazo",
                  (bita_db or {}).get("version_count") == 2,
                  f"got {bita_db.get('version_count') if bita_db else None}")

        # ====== 15. sync_document_deadlines produce fila en document_deadlines =
        rep.section("Upsert dispara sync_document_deadlines → fila en document_deadlines")
        # El primer record que creamos tiene expiry_date a +335d, debe estar en deadlines
        dd_row = db_get(
            "document_deadlines",
            "source_table='expediente_records' AND source_id=? AND brand='petroleum'",
            (rec_id,),
        )
        rep.check("document_deadlines tiene fila para el expediente creado",
                  dd_row is not None,
                  f"got row={dd_row}")
        if dd_row:
            rep.check("dd_row.station_id apunta a la estación correcta",
                      dd_row.get("station_id") == sid_pet)

        # ====== 16. Scoping: jefe ve sólo SU estación ==========================
        rep.section("Jefe sólo ve expediente de SU estación (group scope)")
        # Crear estación adicional de petroleum CON GRUPO DISTINTO
        sid_other = insert_extra_station("petroleum", "P-OTRA-F", "Otra Petroleum F", group_name="X")
        # Admin crea un registro en esa estación
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        resp = env.client.post("/api/expedientes/records", json={
            "area": "normativas",
            "station_id": sid_other,
            "template_id": tpl_permiso_id,
            "status": "vigente",
            "issue_date": days_from_today(-10),
        })
        rep.check("admin crea record en P-OTRA-F → 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        # jefe_pet (group='Demo') intenta consultar P-OTRA-F → 403
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")
        resp = env.client.get(f"/api/expedientes/items?area=normativas&station_id={sid_other}")
        rep.check("jefe_pet → items de P-OTRA-F → 403",
                  resp.status_code == 403,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        rep.check("error='forbidden_station'",
                  (resp.get_json() or {}).get("error") == "forbidden_station")

        # jefe_pet → SU estación → 200
        resp = env.client.get(f"/api/expedientes/items?area=normativas&station_id={sid_pet}")
        rep.check("jefe_pet → items de SU estación → 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        items_je = (resp.get_json() or {}).get("items") or []
        rep.check("jefe_pet ve sus 6 items (mismos que admin)",
                  len(items_je) == 6 + 1,  # 6 seed + extra_test
                  f"got {len(items_je)} items")

        # ====== 17. Cross-station write rejection ==============================
        rep.section("Jefe NO puede crear record en estación ajena (cross-station)")
        resp = env.client.post("/api/expedientes/records", json={
            "area": "normativas",
            "station_id": sid_other,
            "template_id": tpl_permiso_id,
            "status": "vigente",
        })
        rep.check("jefe_pet → POST record para P-OTRA-F → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 18. Versions: jefe NO ve versions de records ajenos ============
        rep.section("Jefe NO accede a versions de records de otra estación")
        # admin sube archivo al record de P-OTRA-F para que tenga versiones
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        other_rec = db_get("expediente_records",
                            "station_id=? AND template_id=?",
                            (sid_other, tpl_permiso_id))
        rep.check("record de P-OTRA-F encontrado en BD",
                  other_rec is not None)
        if other_rec:
            other_rec_id = int(other_rec.get("id"))
            data = {
                "file": (io.BytesIO(fake_pdf_bytes()), "permiso.pdf"),
            }
            env.client.post(
                f"/api/expedientes/{other_rec_id}/file",
                data=data, content_type="multipart/form-data",
            )
            login(env, "jefe_pet", "jefe123")
            set_session_brand(env, "petroleum")
            resp = env.client.get(f"/api/expedientes/{other_rec_id}/versions")
            rep.check("jefe_pet → versions ajenas → 403",
                      resp.status_code == 403, f"got {resp.status_code}")
            resp = env.client.post(
                f"/api/expedientes/{other_rec_id}/file",
                data={"file": (io.BytesIO(b"%PDF-1.4"), "x.pdf")},
                content_type="multipart/form-data",
            )
            rep.check("jefe_pet → upload a record ajeno → 403",
                      resp.status_code == 403, f"got {resp.status_code}")

        # ====== 19. NO PROBAR — Confirmar que ZIP export es un GAP =============
        rep.section("Gap documentado: NO existe endpoint de ZIP export del expediente")
        # Si en el futuro alguien lo implementa, queremos que este check ROMPA
        # para forzar a actualizar el plan de pruebas.
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        for url in [
            f"/api/expedientes/{rec_id}/zip",
            f"/api/expedientes/{rec_id}/export.zip",
            f"/api/expedientes/export.zip?area=normativas&station_id={sid_pet}",
            f"/api/expedientes/{sid_pet}/zip",
        ]:
            resp = env.client.get(url)
            rep.check(f"{url} → 404 (gap conocido; si pasa a 200 actualizar plan)",
                      resp.status_code == 404,
                      f"got {resp.status_code}; si es 200, el feature fue implementado y este test ya no aplica")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

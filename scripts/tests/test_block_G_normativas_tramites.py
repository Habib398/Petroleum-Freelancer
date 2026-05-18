"""Bloque G · Normativas y Trámites (cap. 3.1–3.3 de la propuesta)

Verifica el CRUD del módulo de **normativas** (petroleum) y reafirma que
la rama de **trámites** (consulting) está cerrada por feature-flag.

A diferencia de Bloque E (que trabaja sobre el calendario de vencimientos
generado por ``sync_document_deadlines``), este bloque cubre la tabla
``normativas`` directamente: meta/taxonomía, listado con filtros y
búsqueda, creación con catálogo, actualización parcial vía PATCH,
subida de evidencia, exportación CSV y el catálogo administrable.

Decisión de diseño confirmada por código: **todos** los endpoints
``/api/normativas/*`` están marcados ``@role_required('admin')``. El
jefe_estacion únicamente ve normativas en el calendario de vencimientos
(Bloque E). Aquí validamos que esa puerta esté efectivamente cerrada.

Áreas cubiertas:

* ``GET /api/normativas/meta`` devuelve taxonomía completa (statuses,
  periodicities, risks, categories), catálogo seed y estaciones.
* ``GET /api/normativas/catalog`` y ``POST /catalog`` (catálogo de
  plantillas administrables).
* ``GET /api/normativas`` con filtros: status, station_id, q (texto).
* ``POST /api/normativas`` — validaciones (station_required,
  station_not_found, catalog_not_found, coerción de status/periodicity/
  risk fuera de dominio).
* Auto-cálculo de ``next_due_date`` cuando no se proporciona, usando
  ``periodicity`` y ``compliance_date``.
* Cuando se pasa ``catalog_id``, los campos no proporcionados se
  heredan de la plantilla de catálogo.
* ``PATCH /api/normativas/<id>`` updates parciales, ignora valores
  fuera de dominio, 404 cuando no existe.
* ``POST /api/normativas/<id>/evidence`` sube archivo, persiste
  ``evidence_path``.
* ``GET /api/normativas/export.csv`` devuelve CSV con headers correctos.
* ``sync_document_deadlines`` se dispara tras create y update.
* **Role gate**: jefe_estacion → 403 en todos los endpoints.
* **Tramites cerrado**: cada ruta ``/api/tramites/*`` devuelve 410
  ``tramites_disabled``.
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


def fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n% test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def main() -> int:
    rep = TestReporter("Bloque G · Normativas y Trámites")
    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_pet = baseline.station_petroleum_id

        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")

        # ====== 1. GET /api/normativas/meta — taxonomía completa ===============
        rep.section("GET /api/normativas/meta devuelve taxonomía y catálogo")
        resp = env.client.get("/api/normativas/meta")
        rep.check("meta → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        meta = resp.get_json() or {}
        rep.check("meta.ok=True", meta.get("ok") is True)
        statuses = meta.get("statuses") or []
        rep.check("statuses incluye los 6 estados de normativas",
                  {"cumple", "proximo_a_vencer", "vencido",
                   "en_proceso", "no_aplica", "en_revision"}.issubset(set(statuses)),
                  f"got {statuses}")
        periodicities = meta.get("periodicities") or []
        rep.check("periodicities incluye los 6 valores estándar",
                  {"mensual", "bimestral", "trimestral",
                   "semestral", "anual", "eventual"}.issubset(set(periodicities)),
                  f"got {periodicities}")
        risks = meta.get("risks") or []
        rep.check("risks tiene exactamente 4 niveles",
                  set(risks) == {"bajo", "medio", "alto", "critico"},
                  f"got {risks}")
        categories = meta.get("categories") or []
        rep.check("categories incluye 'Seguridad' y 'Documentacion legal'",
                  {"Seguridad", "Documentacion legal"}.issubset(set(categories)),
                  f"got {categories}")
        catalog = meta.get("catalog") or []
        rep.check("catalog tiene ≥1 plantilla seed (después del branding filter)",
                  len(catalog) >= 1,
                  f"got {len(catalog)} entries")
        rep.check("meta.can_manage_catalog == True para admin",
                  meta.get("can_manage_catalog") is True)
        stations = meta.get("stations") or []
        rep.check("meta.stations incluye la estación petroleum baseline",
                  any(s.get("id") == sid_pet for s in stations))

        # ====== 2. GET /catalog estándalone ====================================
        rep.section("GET /api/normativas/catalog devuelve catálogo")
        resp = env.client.get("/api/normativas/catalog")
        rep.check("catalog → 200", resp.status_code == 200)
        items = (resp.get_json() or {}).get("items") or []
        rep.check("catalog items ≥ 1", len(items) >= 1)
        # Mismo número que meta.catalog (consistencia)
        rep.check("catalog items count == meta.catalog count",
                  len(items) == len(catalog),
                  f"items={len(items)}, meta={len(catalog)}")

        # ====== 3. POST /catalog crea plantilla ================================
        rep.section("POST /api/normativas/catalog crea plantilla nueva")
        resp = env.client.post("/api/normativas/catalog", json={
            "code": "test_nueva_norma",
            "title": "Plantilla de prueba G",
            "category": "Inspeccion",
            "description": "Prueba de bloque G",
            "periodicity": "trimestral",
            "default_risk": "alto",
            "sort_order": 999,
        })
        rep.check("catalog POST → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        new_cat_id = (resp.get_json() or {}).get("id")
        rep.check("body.id es int", isinstance(new_cat_id, int))
        cat_db = db_get("normative_catalog", "id=?", (new_cat_id,))
        rep.check("catalog row persistido con brand=petroleum",
                  (cat_db or {}).get("brand") == "petroleum")
        rep.check("catalog.title persistido",
                  (cat_db or {}).get("title") == "Plantilla de prueba G")

        # ====== 4. POST /catalog sin título → 400 =============================
        resp = env.client.post("/api/normativas/catalog", json={
            "category": "Seguridad",
        })
        rep.check("catalog POST sin título → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='missing_title'",
                  (resp.get_json() or {}).get("error") == "missing_title")

        # ====== 5. GET /api/normativas vacío inicial ===========================
        rep.section("GET /api/normativas devuelve lista (inicial vacía)")
        resp = env.client.get("/api/normativas")
        rep.check("normativas list → 200", resp.status_code == 200)
        rep.check("items inicialmente vacío",
                  (resp.get_json() or {}).get("items") == [])

        # ====== 6. POST /api/normativas — validaciones =========================
        rep.section("POST /api/normativas — validaciones de input")
        # 6.1 sin station_id → 400
        resp = env.client.post("/api/normativas", json={"norma_title": "X"})
        rep.check("POST sin station_id → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='station_required'",
                  (resp.get_json() or {}).get("error") == "station_required")
        # 6.2 station_id no existente → 404
        resp = env.client.post("/api/normativas", json={
            "station_id": 99999, "norma_title": "X",
        })
        rep.check("POST con station_id inexistente → 404",
                  resp.status_code == 404)
        rep.check("error='station_not_found'",
                  (resp.get_json() or {}).get("error") == "station_not_found")
        # 6.3 station_id de estación consulting → 404 (filtrado por brand)
        resp = env.client.post("/api/normativas", json={
            "station_id": baseline.station_consulting_id, "norma_title": "X",
        })
        rep.check("POST con station_id consulting → 404 (filtrado por brand=petroleum)",
                  resp.status_code == 404,
                  f"got {resp.status_code}")
        # 6.4 catalog_id no existente → 404
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet,
            "catalog_id": 99999,
            "norma_title": "X",
        })
        rep.check("POST con catalog_id inexistente → 404",
                  resp.status_code == 404)
        rep.check("error='catalog_not_found'",
                  (resp.get_json() or {}).get("error") == "catalog_not_found")

        # ====== 7. POST /api/normativas — creación válida =====================
        rep.section("POST /api/normativas crea normativa con campos completos")
        compliance = days_from_today(-30)
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet,
            "norma_title": "Inspección NOM-005 mensual",
            "category": "Seguridad",
            "description": "Inspección mensual de seguridad",
            "periodicity": "mensual",
            "compliance_date": compliance,
            "next_due_date": days_from_today(0),
            "status": "en_proceso",
            "risk_level": "alto",
            "observations": "Pendiente cierre de observación 3",
            "responsible_user_id": baseline.jefe_pet_id,
        })
        rep.check("POST normativa → 200", resp.status_code == 200,
                  f"got {resp.status_code}")
        body = resp.get_json() or {}
        rep.check("body.ok=True y body.id presente",
                  body.get("ok") is True and isinstance(body.get("id"), int))
        n1_id = int(body.get("id"))
        n1_db = db_get("normativas", "id=?", (n1_id,))
        rep.check("normativa persistida con brand=petroleum",
                  (n1_db or {}).get("brand") == "petroleum")
        rep.check("status, risk y periodicity persistidos",
                  (n1_db or {}).get("status") == "en_proceso"
                  and (n1_db or {}).get("risk_level") == "alto"
                  and (n1_db or {}).get("periodicity") == "mensual")
        rep.check("responsible_user_id == jefe_pet",
                  (n1_db or {}).get("responsible_user_id") == baseline.jefe_pet_id)
        rep.check("reminder_days default = '60,30,15,7,3,1,0'",
                  (n1_db or {}).get("reminder_days") == "60,30,15,7,3,1,0")

        # ====== 8. Coerción de valores fuera de dominio =======================
        rep.section("Valores fuera de dominio se coercen a default")
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet,
            "norma_title": "Norma con valores inválidos",
            "status": "estado_inventado",
            "periodicity": "cada_luna_llena",
            "risk_level": "extremo",
            "compliance_date": compliance,
        })
        rep.check("POST → 200 (acepta y coerce)",
                  resp.status_code == 200)
        bad_id = int((resp.get_json() or {}).get("id"))
        bad_db = db_get("normativas", "id=?", (bad_id,))
        rep.check("status coercido a 'en_proceso'",
                  (bad_db or {}).get("status") == "en_proceso",
                  f"got {bad_db.get('status') if bad_db else None}")
        rep.check("periodicity coercida a 'eventual'",
                  (bad_db or {}).get("periodicity") == "eventual",
                  f"got {bad_db.get('periodicity') if bad_db else None}")
        rep.check("risk_level coercido a 'medio'",
                  (bad_db or {}).get("risk_level") == "medio",
                  f"got {bad_db.get('risk_level') if bad_db else None}")

        # ====== 9. Auto-cálculo de next_due_date desde periodicity =============
        rep.section("next_due_date se autocalcula desde periodicity si no se pasa")
        compliance_auto = days_from_today(0)
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet,
            "norma_title": "Calibración trimestral",
            "periodicity": "trimestral",
            "compliance_date": compliance_auto,
            # next_due_date omitido a propósito
        })
        rep.check("POST sin next_due_date → 200",
                  resp.status_code == 200)
        auto_id = int((resp.get_json() or {}).get("id"))
        auto_db = db_get("normativas", "id=?", (auto_id,))
        # +3 meses de la fecha de hoy
        rep.check("next_due_date calculado (~3 meses después)",
                  bool((auto_db or {}).get("next_due_date"))
                  and (auto_db or {}).get("next_due_date") > compliance_auto,
                  f"got next_due_date={auto_db.get('next_due_date') if auto_db else None}")

        # ====== 10. Catálogo: catalog_id hereda campos no proporcionados ======
        rep.section("catalog_id hereda title/category/periodicity/risk si no se pasan")
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet,
            "catalog_id": new_cat_id,
            # no pasamos title/category/periodicity/risk
            "compliance_date": days_from_today(-5),
        })
        rep.check("POST con catalog_id → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        cat_norm_id = int((resp.get_json() or {}).get("id"))
        cat_norm_db = db_get("normativas", "id=?", (cat_norm_id,))
        rep.check("norma_title heredado del catálogo",
                  (cat_norm_db or {}).get("norma_title") == "Plantilla de prueba G",
                  f"got {cat_norm_db.get('norma_title') if cat_norm_db else None}")
        rep.check("category heredado: 'Inspeccion'",
                  (cat_norm_db or {}).get("category") == "Inspeccion")
        rep.check("periodicity heredado: 'trimestral'",
                  (cat_norm_db or {}).get("periodicity") == "trimestral")
        rep.check("risk_level heredado: 'alto'",
                  (cat_norm_db or {}).get("risk_level") == "alto")
        rep.check("catalog_id vinculado en la normativa",
                  (cat_norm_db or {}).get("catalog_id") == new_cat_id)

        # ====== 11. GET /api/normativas — filtros ============================
        rep.section("GET con filtros (status, station_id, q)")
        resp = env.client.get("/api/normativas")
        all_items = (resp.get_json() or {}).get("items") or []
        rep.check("lista incluye las 4 normativas creadas",
                  len(all_items) >= 4, f"got {len(all_items)}")

        # 11.1 filter por status
        resp = env.client.get("/api/normativas?status=en_proceso")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("filter status=en_proceso → solo en_proceso",
                  rows and all(r.get("status") == "en_proceso" for r in rows),
                  f"got statuses={[r.get('status') for r in rows]}")
        # 11.2 filter por station_id (sólo hay una estación pet con normativas)
        resp = env.client.get(f"/api/normativas?station_id={sid_pet}")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("filter station_id → solo de esa estación",
                  rows and all(r.get("station_id") == sid_pet for r in rows))
        # 11.3 búsqueda full-text por title
        resp = env.client.get("/api/normativas?q=NOM-005")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("q=NOM-005 encuentra la normativa con ese texto",
                  any("NOM-005" in (r.get("norma_title") or "") for r in rows),
                  f"got titles={[r.get('norma_title') for r in rows]}")
        # 11.4 búsqueda en observations
        resp = env.client.get("/api/normativas?q=observación")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("q='observación' encuentra normativas con observaciones",
                  len(rows) >= 1,
                  f"got {len(rows)} rows")

        # ====== 12. PATCH /api/normativas/<id> — update parcial ===============
        rep.section("PATCH actualiza campos permitidos")
        resp = env.client.patch(f"/api/normativas/{n1_id}", json={
            "status": "cumple",
            "observations": "Cierre confirmado",
            "risk_level": "medio",
        })
        rep.check("PATCH → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        n1_db = db_get("normativas", "id=?", (n1_id,))
        rep.check("status actualizado a 'cumple'",
                  (n1_db or {}).get("status") == "cumple")
        rep.check("observations actualizadas",
                  (n1_db or {}).get("observations") == "Cierre confirmado")
        rep.check("risk_level actualizado a 'medio'",
                  (n1_db or {}).get("risk_level") == "medio")
        rep.check("norma_title NO se tocó (campo no enviado)",
                  (n1_db or {}).get("norma_title") == "Inspección NOM-005 mensual")

        # ====== 13. PATCH — valores fuera de dominio se ignoran ===============
        rep.section("PATCH ignora valores fuera de dominio (no rompe el update)")
        resp = env.client.patch(f"/api/normativas/{n1_id}", json={
            "status": "estado_invalido",
            "observations": "Update parcial OK",
        })
        rep.check("PATCH con status inválido → 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        n1_db = db_get("normativas", "id=?", (n1_id,))
        rep.check("status conservado en 'cumple' (no se cambió por inválido)",
                  (n1_db or {}).get("status") == "cumple")
        rep.check("observations sí se actualizaron",
                  (n1_db or {}).get("observations") == "Update parcial OK")

        # ====== 14. PATCH a id inexistente → 404 ==============================
        resp = env.client.patch("/api/normativas/99999", json={"status": "cumple"})
        rep.check("PATCH a id inexistente → 404",
                  resp.status_code == 404)
        rep.check("error='not_found'",
                  (resp.get_json() or {}).get("error") == "not_found")

        # ====== 15. POST /<id>/evidence sube archivo ==========================
        rep.section("POST /<id>/evidence sube evidencia y persiste path")
        data = {
            "file": (io.BytesIO(fake_pdf_bytes()), "evidencia_nom005.pdf"),
        }
        resp = env.client.post(
            f"/api/normativas/{n1_id}/evidence",
            data=data, content_type="multipart/form-data",
        )
        rep.check("evidence POST → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        rep.check("body.evidence_url comienza con /uploads/",
                  (body.get("evidence_url") or "").startswith("/uploads/"))
        n1_db = db_get("normativas", "id=?", (n1_id,))
        rep.check("normativa.evidence_path persistido",
                  bool((n1_db or {}).get("evidence_path")))

        # ====== 16. POST evidence sin archivo → 400 ===========================
        resp = env.client.post(
            f"/api/normativas/{n1_id}/evidence",
            data={}, content_type="multipart/form-data",
        )
        rep.check("evidence sin archivo → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='missing_file'",
                  (resp.get_json() or {}).get("error") == "missing_file")

        # ====== 17. POST evidence a id inexistente → 404 ======================
        resp = env.client.post(
            "/api/normativas/99999/evidence",
            data={"file": (io.BytesIO(fake_pdf_bytes()), "x.pdf")},
            content_type="multipart/form-data",
        )
        rep.check("evidence a id inexistente → 404",
                  resp.status_code == 404)

        # ====== 18. sync_document_deadlines genera filas tras create/update ==
        rep.section("sync_document_deadlines integra normativa al calendario")
        dd_row = db_get(
            "document_deadlines",
            "source_table='normativas' AND source_id=? AND brand='petroleum'",
            (n1_id,),
        )
        rep.check("document_deadlines tiene fila para n1",
                  dd_row is not None, f"got {dd_row}")
        if dd_row:
            rep.check("dd_row.station_id apunta a la estación correcta",
                      dd_row.get("station_id") == sid_pet)

        # ====== 19. GET /export.csv ===========================================
        rep.section("GET /api/normativas/export.csv produce CSV con headers correctos")
        resp = env.client.get("/api/normativas/export.csv")
        rep.check("export.csv → 200", resp.status_code == 200)
        rep.check("content-type contiene 'csv'",
                  "csv" in (resp.headers.get("Content-Type") or "").lower(),
                  f"got {resp.headers.get('Content-Type')!r}")
        rep.check("filename incluye 'normativas_petroleum'",
                  "normativas_petroleum" in (resp.headers.get("Content-Disposition") or ""),
                  f"got {resp.headers.get('Content-Disposition')!r}")
        csv_text = resp.get_data(as_text=True)
        first_line = csv_text.splitlines()[0] if csv_text else ""
        rep.check("CSV header incluye 'Folio' y 'Normativa'",
                  "Folio" in first_line and "Normativa" in first_line,
                  f"header={first_line!r}")
        rep.check("CSV incluye al menos una fila con 'NOM-005'",
                  any("NOM-005" in line for line in csv_text.splitlines()),
                  f"lines={len(csv_text.splitlines())}")

        # ====== 20. Role gate: jefe_estacion NO puede usar ningún endpoint ===
        rep.section("Role gate: jefe_estacion → 403 en TODOS los /api/normativas/*")
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")

        endpoints_403 = [
            ("GET",   "/api/normativas/meta",                            None),
            ("GET",   "/api/normativas",                                 None),
            ("GET",   "/api/normativas/catalog",                         None),
            ("GET",   "/api/normativas/export.csv",                      None),
        ]
        for method, path, payload in endpoints_403:
            resp = env.client.open(path, method=method, json=payload)
            rep.check(f"jefe → {method} {path} → 403",
                      resp.status_code == 403,
                      f"got {resp.status_code}")

        # mutating endpoints
        resp = env.client.post("/api/normativas", json={
            "station_id": sid_pet, "norma_title": "Intento de jefe",
        })
        rep.check("jefe → POST /api/normativas → 403",
                  resp.status_code == 403, f"got {resp.status_code}")
        resp = env.client.patch(f"/api/normativas/{n1_id}", json={"status": "cumple"})
        rep.check("jefe → PATCH /api/normativas/<id> → 403",
                  resp.status_code == 403, f"got {resp.status_code}")
        resp = env.client.post(f"/api/normativas/{n1_id}/evidence",
                                data={"file": (io.BytesIO(b"%PDF"), "x.pdf")},
                                content_type="multipart/form-data")
        rep.check("jefe → POST /<id>/evidence → 403",
                  resp.status_code == 403, f"got {resp.status_code}")
        resp = env.client.post("/api/normativas/catalog", json={"title": "X"})
        rep.check("jefe → POST /api/normativas/catalog → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

        # ====== 21. Trámites — TODOS los endpoints devuelven 410 =============
        rep.section("Rama 'tramites' (consulting) cerrada por feature-flag → 410")
        login(env, "admin", "admin123")
        set_session_brand(env, "consulting")

        tramites_endpoints = [
            ("GET",   "/api/tramites/meta",                              None),
            ("GET",   "/api/tramites",                                   None),
            ("POST",  "/api/tramites",                                   {"station_id": baseline.station_consulting_id}),
            ("PATCH", "/api/tramites/1",                                 {"status": "vigente"}),
            ("GET",   "/api/tramites/export.csv",                        None),
            ("GET",   "/api/tramites/control-documental",                None),
            ("GET",   "/api/tramites/control-documental/export.csv",     None),
        ]
        for method, path, payload in tramites_endpoints:
            resp = env.client.open(path, method=method, json=payload)
            rep.check(f"admin → {method} {path} → 410",
                      resp.status_code == 410,
                      f"got {resp.status_code}")
            body = resp.get_json() or {}
            rep.check(f"{path} → error='tramites_disabled'",
                      body.get("error") == "tramites_disabled")

        # 21.1 attachment también
        resp = env.client.post("/api/tramites/1/attachment",
                                data={"file": (io.BytesIO(b"%PDF"), "x.pdf")},
                                content_type="multipart/form-data")
        rep.check("POST /api/tramites/1/attachment → 410",
                  resp.status_code == 410, f"got {resp.status_code}")

        # 21.2 my-expediente (jefe/operador) también
        login(env, "jefe_test", "jefe123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/tramites/my-expediente")
        rep.check("jefe → GET /api/tramites/my-expediente → 410",
                  resp.status_code == 410, f"got {resp.status_code}")
        resp = env.client.post("/api/tramites/my-expediente/records",
                                json={"template_id": 1, "title": "X"})
        rep.check("jefe → POST /api/tramites/my-expediente/records → 410",
                  resp.status_code == 410, f"got {resp.status_code}")

        # ====== 22. Total de normativas creadas (consistencia BD) ============
        rep.section("Consistencia: total normativas en BD == lo creado")
        total = db_row_count("normativas", "brand='petroleum'", ())
        rep.check("normativas total == 4 (las que insertamos)",
                  total == 4, f"got {total}")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

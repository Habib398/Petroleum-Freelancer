"""Bloque H · Petroleum — Control de vigencias (cap. 5 de la propuesta)

Verifica el módulo de control de vigencias por estación petroleum:
catálogo de **responsables** (``petroleum_owner_catalog``), catálogo de
**tipos de documento** (``petroleum_doc_types``) y la tabla
``petroleum_station_control`` que cruza ambos para tener una fila por
(estación × documento) con sus fechas y estatus.

A diferencia del módulo de normativas (Bloque G), aquí la lógica de
**estatus de renovación** se computa al vuelo desde ``renewal_date``:
``vigente`` (>30 días), ``proximo`` (≤30 días), ``vencido`` (<0 días),
``sin_fecha``. Esto es un campo derivado, no persistido — el test valida
el comportamiento del cómputo en cada bucket.

Cross-cutting:

* **Brand gate**: todos los endpoints exigen ``brand=petroleum`` activo
  en sesión. Si la sesión está en ``consulting`` → 403 ``forbidden``.
* **Role gate**: ``@role_required('admin')`` en todo el módulo. Jefe →
  403 sin pasar por el brand gate (decorador anterior).

Áreas cubiertas:

* ``GET /api/petroleum/control/meta``: owners, stations, doc_types,
  summary con KPIs (vigentes, por_vencer, vencidos, pagos_pendientes,
  documentos_pendientes).
* ``POST /owners`` crea responsable (name+short_code obligatorios; el
  short_code es único, duplicado → 400).
* ``PATCH /owners/<id>`` actualiza; sin campos → 400.
* ``POST /doc-types`` crea tipo (code+title obligatorios; code duplicado
  → 400).
* ``POST /stations/<id>/owner`` asigna o desasigna responsable (con
  ``owner_id=null`` desasigna).
* ``POST /entries`` upsert (ON CONFLICT por (station_id, doc_type_id)).
  Idempotente: segundo POST con misma combinación actualiza, no crea.
* ``PATCH /entries/<id>`` valida dominios (status/payment fuera de
  catálogo se ignoran, no rompen).
* ``GET /entries`` filtra por owner, station, doc_type, renewal_state,
  payment_status.
* Cómputo de ``renewal_state`` correcto en los 4 buckets: vigente,
  proximo, vencido, sin_fecha (y ``days_left`` coherente).
* ``attention_flags`` (document/payment/renewal) reflejan el estado real.
* Summary KPIs cuadran con los conteos derivados.
"""

from __future__ import annotations

import datetime as _dt
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


def insert_extra_station(brand: str, code: str, name: str,
                          group_name: str | None = None,
                          station_number: str | None = None) -> int:
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name) VALUES (?,?,?,?,?)",
        (brand, name, code, station_number or code, group_name),
    )
    sid = int(cur.lastrowid)
    conn.commit(); conn.close()
    return sid


def main() -> int:
    rep = TestReporter("Bloque H · Petroleum control de vigencias")
    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_pet = baseline.station_petroleum_id

        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")

        # ====== 1. Auto-activación de brand=petroleum en /api/petroleum/* =====
        # before_request en app.py auto-switchea brand="petroleum" cuando la
        # URL empieza con /api/petroleum/ y el usuario tiene esa marca permitida.
        # Resultado: el guard _ensure_brand_petroleum() rara vez dispara para
        # admin (allowed: consulting+petroleum). Documentamos ese comportamiento.
        rep.section("Auto-activación de brand=petroleum al entrar a /api/petroleum/*")
        set_session_brand(env, "consulting")
        with env.client.session_transaction() as s:
            rep.check("brand pre-request == 'consulting'",
                      s.get("brand") == "consulting")
        resp = env.client.get("/api/petroleum/control/meta")
        rep.check("admin → meta con brand consulting → 200 (auto-switch)",
                  resp.status_code == 200, f"got {resp.status_code}")
        with env.client.session_transaction() as s:
            rep.check("brand post-request == 'petroleum' (auto-activado)",
                      s.get("brand") == "petroleum",
                      f"got {s.get('brand')!r}")

        # ====== 2. GET /api/petroleum/control/meta — seed inicial =============
        rep.section("GET /meta devuelve owners, stations, doc_types y summary")
        resp = env.client.get("/api/petroleum/control/meta")
        rep.check("meta → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        meta = resp.get_json() or {}
        rep.check("meta.ok=True", meta.get("ok") is True)
        owners = meta.get("owners") or []
        rep.check("owners inicial = vacío",
                  owners == [], f"got {len(owners)}")
        stations = meta.get("stations") or []
        rep.check("stations incluye la estación petroleum baseline",
                  any(s.get("id") == sid_pet for s in stations))
        doc_types = meta.get("doc_types") or []
        rep.check("doc_types tiene los 3 seed (nom005, nom016, anexo3031)",
                  len(doc_types) == 3, f"got {len(doc_types)}")
        seed_codes = {(t.get("code") or "") for t in doc_types}
        rep.check("doc_types incluye nom005, nom016, anexo3031",
                  {"nom005", "nom016", "anexo3031"}.issubset(seed_codes),
                  f"got {seed_codes}")
        summary = meta.get("summary") or {}
        rep.check("summary tiene las claves esperadas",
                  set(summary.keys()) >= {"total", "vigentes", "por_vencer",
                                            "vencidos", "pagos_pendientes",
                                            "documentos_pendientes"},
                  f"got {set(summary.keys())}")
        rep.check("summary.total == 0 (no hay entries aún)",
                  summary.get("total") == 0, f"got {summary}")

        # ====== 3. POST /owners crea responsable ==============================
        rep.section("POST /owners crea responsable nuevo")
        resp = env.client.post("/api/petroleum/control/owners", json={
            "name": "Grupo Demo Pet", "short_code": "GDP",
            "color_hex": "#FF8800",
            "phone": "55-1234-5678", "email": "demo@example.com",
            "notes": "Responsable de prueba",
        })
        rep.check("POST owner → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        owner_id = (resp.get_json() or {}).get("id")
        rep.check("body.id es int", isinstance(owner_id, int))
        owner_db = db_get("petroleum_owner_catalog", "id=?", (owner_id,))
        rep.check("owner persistido con name='Grupo Demo Pet'",
                  (owner_db or {}).get("name") == "Grupo Demo Pet")
        rep.check("short_code uppercased",
                  (owner_db or {}).get("short_code") == "GDP")

        # 3.1 sin name/short_code → 400
        resp = env.client.post("/api/petroleum/control/owners", json={"name": ""})
        rep.check("POST owner sin name/short_code → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='bad_request'",
                  (resp.get_json() or {}).get("error") == "bad_request")

        # 3.2 short_code duplicado → 400
        resp = env.client.post("/api/petroleum/control/owners", json={
            "name": "Otro nombre", "short_code": "gdp",  # mismo en lowercase
        })
        rep.check("POST owner con short_code duplicado → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        rep.check("error='duplicate'",
                  (resp.get_json() or {}).get("error") == "duplicate")

        # ====== 4. PATCH /owners/<id> actualiza ===============================
        rep.section("PATCH /owners/<id> actualiza campos del responsable")
        resp = env.client.patch(f"/api/petroleum/control/owners/{owner_id}", json={
            "phone": "55-9999-0000", "notes": "Actualizado por test",
        })
        rep.check("PATCH owner → 200", resp.status_code == 200,
                  f"got {resp.status_code}")
        owner_db = db_get("petroleum_owner_catalog", "id=?", (owner_id,))
        rep.check("phone actualizado",
                  (owner_db or {}).get("phone") == "55-9999-0000")
        rep.check("notes actualizadas",
                  (owner_db or {}).get("notes") == "Actualizado por test")
        rep.check("name NO se tocó",
                  (owner_db or {}).get("name") == "Grupo Demo Pet")

        # 4.1 PATCH sin campos → 400 no_changes
        resp = env.client.patch(f"/api/petroleum/control/owners/{owner_id}", json={})
        rep.check("PATCH sin campos → 400",
                  resp.status_code == 400)
        rep.check("error='no_changes'",
                  (resp.get_json() or {}).get("error") == "no_changes")

        # ====== 5. POST /stations/<id>/owner asigna responsable ===============
        rep.section("POST /stations/<id>/owner asigna/desasigna responsable")
        resp = env.client.post(
            f"/api/petroleum/control/stations/{sid_pet}/owner",
            json={"owner_id": owner_id},
        )
        rep.check("asignar owner → 200", resp.status_code == 200)
        st_db = db_get("stations", "id=?", (sid_pet,))
        rep.check("stations.petroleum_owner_id se persistió",
                  (st_db or {}).get("petroleum_owner_id") == owner_id)

        # 5.1 desasignar pasando owner_id=null
        resp = env.client.post(
            f"/api/petroleum/control/stations/{sid_pet}/owner",
            json={"owner_id": None},
        )
        rep.check("desasignar owner (null) → 200", resp.status_code == 200)
        st_db = db_get("stations", "id=?", (sid_pet,))
        rep.check("petroleum_owner_id quedó NULL",
                  (st_db or {}).get("petroleum_owner_id") is None)

        # Re-asignar para los tests siguientes
        env.client.post(
            f"/api/petroleum/control/stations/{sid_pet}/owner",
            json={"owner_id": owner_id},
        )

        # ====== 6. POST /doc-types crea tipo de documento ====================
        rep.section("POST /doc-types crea un tipo de documento nuevo")
        resp = env.client.post("/api/petroleum/control/doc-types", json={
            "code": "fiel_test", "title": "FIEL (test)",
            "accent_color": "#22CCEE", "sort_order": 999,
        })
        rep.check("POST doc-type → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        new_dt_id = (resp.get_json() or {}).get("id")
        rep.check("body.id devuelto", isinstance(new_dt_id, int))
        dt_db = db_get("petroleum_doc_types", "id=?", (new_dt_id,))
        rep.check("doc_type persistido con code='fiel_test'",
                  (dt_db or {}).get("code") == "fiel_test")

        # 6.1 sin code o title → 400
        resp = env.client.post("/api/petroleum/control/doc-types", json={"code": "x"})
        rep.check("doc-type sin title → 400",
                  resp.status_code == 400)
        rep.check("error='bad_request'",
                  (resp.get_json() or {}).get("error") == "bad_request")

        # 6.2 code duplicado → 400
        resp = env.client.post("/api/petroleum/control/doc-types", json={
            "code": "fiel_test", "title": "duplicada",
        })
        rep.check("doc-type code duplicado → 400",
                  resp.status_code == 400)
        rep.check("error='duplicate'",
                  (resp.get_json() or {}).get("error") == "duplicate")

        # ====== 7. POST /entries crea (upsert) ================================
        rep.section("POST /entries crea registro de control documental")
        # Necesitamos los IDs de los doc_types seed
        dt_nom005 = next((t for t in doc_types if t.get("code") == "nom005"), None)
        dt_nom016 = next((t for t in doc_types if t.get("code") == "nom016"), None)
        dt_anexo = next((t for t in doc_types if t.get("code") == "anexo3031"), None)
        rep.check("doc_types seed encontrados",
                  all(x is not None for x in (dt_nom005, dt_nom016, dt_anexo)))

        # 7.1 Entry NOM-005: vigente (renewal +90d)
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet,
            "doc_type_id": (dt_nom005 or {}).get("id"),
            "start_date": days_from_today(-30),
            "renewal_date": days_from_today(90),
            "document_status": "vigente",
            "payment_status": "pagado",
            "last_payment_date": days_from_today(-25),
            "amount_due": 1500.0,
            "notes": "Vigente test",
        })
        rep.check("POST entry NOM-005 → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        e1_id = (resp.get_json() or {}).get("id")
        rep.check("body.id devuelto", isinstance(e1_id, int))

        # 7.2 Entry NOM-016: próximo a vencer (+15d)
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet,
            "doc_type_id": (dt_nom016 or {}).get("id"),
            "renewal_date": days_from_today(15),
            "document_status": "vigente",
            "payment_status": "pendiente",
            "amount_due": 2200.0,
        })
        rep.check("POST entry NOM-016 (próximo) → 200", resp.status_code == 200)

        # 7.3 Entry Anexo 30-31: vencido (-10d)
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet,
            "doc_type_id": (dt_anexo or {}).get("id"),
            "renewal_date": days_from_today(-10),
            "document_status": "vencido",
            "payment_status": "vencido",
        })
        rep.check("POST entry Anexo 30-31 (vencido) → 200", resp.status_code == 200)

        # 7.4 Entry FIEL: sin fecha (sin_fecha)
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet,
            "doc_type_id": new_dt_id,
            # renewal_date omitido → sin_fecha
            "document_status": "debe_documento",
            "payment_status": "no_aplica",
        })
        rep.check("POST entry FIEL sin fecha → 200", resp.status_code == 200)

        # ====== 8. Upsert: segundo POST con misma combinación actualiza =======
        rep.section("POST /entries duplicado (mismo station+doc_type) hace upsert")
        prev_count = db_row_count("petroleum_station_control",
                                   "station_id=? AND doc_type_id=?",
                                   (sid_pet, (dt_nom005 or {}).get("id")))
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet,
            "doc_type_id": (dt_nom005 or {}).get("id"),
            "renewal_date": days_from_today(120),  # cambio en fecha
            "document_status": "en_revision",
            "payment_status": "pagado",
            "amount_due": 1800.0,
            "notes": "Actualizado vía upsert",
        })
        rep.check("re-POST NOM-005 → 200", resp.status_code == 200)
        new_count = db_row_count("petroleum_station_control",
                                  "station_id=? AND doc_type_id=?",
                                  (sid_pet, (dt_nom005 or {}).get("id")))
        rep.check("count NO cambió (upsert, no insert)",
                  new_count == prev_count, f"prev={prev_count}, new={new_count}")
        e1_db = db_get("petroleum_station_control", "id=?", (e1_id,))
        rep.check("document_status actualizado a 'en_revision'",
                  (e1_db or {}).get("document_status") == "en_revision")
        rep.check("amount_due actualizado a 1800.0",
                  (e1_db or {}).get("amount_due") == 1800.0)
        rep.check("notes actualizadas",
                  (e1_db or {}).get("notes") == "Actualizado vía upsert")

        # ====== 9. POST entries — validaciones ================================
        rep.section("POST /entries — validaciones de input")
        # 9.1 sin station/doc_type → 400
        resp = env.client.post("/api/petroleum/control/entries", json={})
        rep.check("POST entries vacío → 400",
                  resp.status_code == 400)
        rep.check("error='bad_request'",
                  (resp.get_json() or {}).get("error") == "bad_request")

        # 9.2 station_id inexistente → 404
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": 99999,
            "doc_type_id": (dt_nom005 or {}).get("id"),
        })
        rep.check("station_id inexistente → 404", resp.status_code == 404)
        rep.check("error='not_found'",
                  (resp.get_json() or {}).get("error") == "not_found")

        # 9.3 doc_type inexistente → 404
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": sid_pet, "doc_type_id": 99999,
        })
        rep.check("doc_type inexistente → 404", resp.status_code == 404)

        # 9.4 estación consulting → 404 (filtrada por brand)
        resp = env.client.post("/api/petroleum/control/entries", json={
            "station_id": baseline.station_consulting_id,
            "doc_type_id": (dt_nom005 or {}).get("id"),
        })
        rep.check("station consulting → 404 (filtro por brand)",
                  resp.status_code == 404,
                  f"got {resp.status_code}")

        # ====== 10. PATCH /entries/<id> ========================================
        rep.section("PATCH /entries/<id> actualiza campos parciales")
        resp = env.client.patch(f"/api/petroleum/control/entries/{e1_id}", json={
            "document_status": "vigente",
            "amount_due": 2500.0,
        })
        rep.check("PATCH entry → 200", resp.status_code == 200,
                  f"got {resp.status_code}")
        e1_db = db_get("petroleum_station_control", "id=?", (e1_id,))
        rep.check("document_status actualizado a 'vigente'",
                  (e1_db or {}).get("document_status") == "vigente")
        rep.check("amount_due actualizado a 2500.0",
                  (e1_db or {}).get("amount_due") == 2500.0)

        # 10.1 PATCH con valores inválidos: se ignoran (no rompe)
        resp = env.client.patch(f"/api/petroleum/control/entries/{e1_id}", json={
            "document_status": "estado_inventado",
            "payment_status": "no_existe",
            "notes": "Solo notes pasa",
        })
        rep.check("PATCH valores inválidos → 200 (se ignoran)",
                  resp.status_code == 200)
        e1_db = db_get("petroleum_station_control", "id=?", (e1_id,))
        rep.check("document_status conservado en 'vigente'",
                  (e1_db or {}).get("document_status") == "vigente")
        rep.check("notes sí actualizadas",
                  (e1_db or {}).get("notes") == "Solo notes pasa")

        # 10.2 PATCH sin campos → 400 no_changes
        resp = env.client.patch(f"/api/petroleum/control/entries/{e1_id}", json={})
        rep.check("PATCH sin campos → 400",
                  resp.status_code == 400)

        # ====== 11. GET /entries con cómputo de renewal_state =================
        rep.section("GET /entries computa renewal_state, days_left y attention_flags")
        # Antes del último PATCH, configuramos NOM-005 con +90d again
        env.client.patch(f"/api/petroleum/control/entries/{e1_id}", json={
            "renewal_date": days_from_today(90), "document_status": "vigente",
        })
        resp = env.client.get("/api/petroleum/control/entries")
        rep.check("GET entries → 200", resp.status_code == 200)
        body = resp.get_json() or {}
        items = body.get("items") or []
        rep.check("items trae 4 registros",
                  len(items) == 4, f"got {len(items)}")

        # Buscar cada uno por doc_code y validar su renewal_state esperado
        by_code = {it.get("doc_code"): it for it in items}
        rep.check("NOM-005 (renewal +90d) → renewal_state='vigente'",
                  by_code.get("nom005", {}).get("renewal_state") == "vigente",
                  f"got {by_code.get('nom005', {}).get('renewal_state')!r}")
        rep.check("NOM-016 (+15d) → renewal_state='proximo'",
                  by_code.get("nom016", {}).get("renewal_state") == "proximo",
                  f"got {by_code.get('nom016', {}).get('renewal_state')!r}")
        rep.check("Anexo 30-31 (-10d) → renewal_state='vencido'",
                  by_code.get("anexo3031", {}).get("renewal_state") == "vencido",
                  f"got {by_code.get('anexo3031', {}).get('renewal_state')!r}")
        rep.check("FIEL (sin fecha) → renewal_state='sin_fecha'",
                  by_code.get("fiel_test", {}).get("renewal_state") == "sin_fecha",
                  f"got {by_code.get('fiel_test', {}).get('renewal_state')!r}")

        # days_left coherente
        rep.check("NOM-005 days_left ~ 90",
                  abs((by_code.get("nom005", {}).get("days_left") or 0) - 90) <= 1)
        rep.check("Anexo days_left negativo (~-10)",
                  (by_code.get("anexo3031", {}).get("days_left") or 0) <= 0)
        rep.check("FIEL days_left == None",
                  by_code.get("fiel_test", {}).get("days_left") is None)

        # attention_flags
        anexo_item = by_code.get("anexo3031", {})
        rep.check("Anexo vencido tiene attention_flags.document=True",
                  (anexo_item.get("attention_flags") or {}).get("document") is True)
        rep.check("Anexo vencido tiene attention_flags.renewal=True",
                  (anexo_item.get("attention_flags") or {}).get("renewal") is True)
        rep.check("Anexo vencido tiene attention_flags.payment=True",
                  (anexo_item.get("attention_flags") or {}).get("payment") is True)
        nom005_item = by_code.get("nom005", {})
        rep.check("NOM-005 vigente NO tiene flag.document",
                  (nom005_item.get("attention_flags") or {}).get("document") is False)
        rep.check("NOM-005 vigente NO tiene flag.renewal",
                  (nom005_item.get("attention_flags") or {}).get("renewal") is False)

        # has_owner reflejado
        rep.check("entries tienen has_owner=True (estación con owner asignado)",
                  all(it.get("has_owner") is True for it in items),
                  f"got {[it.get('has_owner') for it in items]}")

        # ====== 12. Filtros del GET /entries ==================================
        rep.section("GET /entries con filtros")
        # 12.1 filter por renewal_state=vencido
        resp = env.client.get("/api/petroleum/control/entries?renewal_state=vencido")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("renewal_state=vencido → solo vencidos",
                  rows and all(r.get("renewal_state") == "vencido" for r in rows),
                  f"got {[r.get('renewal_state') for r in rows]}")

        # 12.2 filter por renewal_state=proximo
        resp = env.client.get("/api/petroleum/control/entries?renewal_state=proximo")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("renewal_state=proximo → solo próximos",
                  rows and all(r.get("renewal_state") == "proximo" for r in rows))

        # 12.3 filter por payment_status=pagado
        resp = env.client.get("/api/petroleum/control/entries?payment_status=pagado")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("payment_status=pagado → solo pagados",
                  rows and all(r.get("payment_status") == "pagado" for r in rows))

        # 12.4 filter por owner_id
        resp = env.client.get(f"/api/petroleum/control/entries?owner_id={owner_id}")
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("owner_id filter → 4 entries (todas de la estación con ese owner)",
                  len(rows) == 4, f"got {len(rows)}")

        # 12.5 filter por doc_type_id
        resp = env.client.get(
            f"/api/petroleum/control/entries?doc_type_id={(dt_nom005 or {}).get('id')}"
        )
        rows = (resp.get_json() or {}).get("items") or []
        rep.check("doc_type_id filter → 1 entry (solo NOM-005)",
                  len(rows) == 1 and (rows[0].get("doc_code") == "nom005"),
                  f"got {[r.get('doc_code') for r in rows]}")

        # ====== 13. Summary KPIs coherentes con entries =======================
        rep.section("Summary KPIs cuadran con los 4 entries existentes")
        resp = env.client.get("/api/petroleum/control/meta")
        meta2 = resp.get_json() or {}
        s = meta2.get("summary") or {}
        rep.check("summary.total == 4",
                  s.get("total") == 4, f"got {s}")
        rep.check("summary.por_vencer == 1 (NOM-016)",
                  s.get("por_vencer") == 1, f"got {s}")
        rep.check("summary.vencidos == 1 (Anexo)",
                  s.get("vencidos") == 1, f"got {s}")
        rep.check("summary.documentos_pendientes == 2 (FIEL debe_documento + Anexo vencido)",
                  s.get("documentos_pendientes") == 2, f"got {s}")
        rep.check("summary.pagos_pendientes == 2 (NOM-016 pendiente + Anexo vencido)",
                  s.get("pagos_pendientes") == 2, f"got {s}")
        rep.check("summary.vigentes == 1 (NOM-005)",
                  s.get("vigentes") == 1, f"got {s}")

        # ====== 14. Role gate: jefe → 403 en todos los endpoints ==============
        rep.section("Role gate: jefe_estacion → 403 en TODOS los endpoints")
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")

        endpoints_403 = [
            ("GET",   "/api/petroleum/control/meta",                       None),
            ("GET",   "/api/petroleum/control/entries",                    None),
            ("POST",  "/api/petroleum/control/owners",                     {"name": "X", "short_code": "X"}),
            ("PATCH", f"/api/petroleum/control/owners/{owner_id}",         {"name": "Y"}),
            ("POST",  f"/api/petroleum/control/stations/{sid_pet}/owner",  {"owner_id": owner_id}),
            ("POST",  "/api/petroleum/control/doc-types",                  {"code": "x", "title": "X"}),
            ("POST",  "/api/petroleum/control/entries",                    {"station_id": sid_pet, "doc_type_id": (dt_nom005 or {}).get("id")}),
            ("PATCH", f"/api/petroleum/control/entries/{e1_id}",           {"notes": "X"}),
        ]
        for method, path, payload in endpoints_403:
            resp = env.client.open(path, method=method, json=payload)
            rep.check(f"jefe → {method} {path} → 403",
                      resp.status_code == 403, f"got {resp.status_code}")

        # ====== 15. Total final en BD =========================================
        rep.section("Consistencia: total entries en BD == 4")
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        total = db_row_count("petroleum_station_control", "1=1", ())
        rep.check("petroleum_station_control total == 4",
                  total == 4, f"got {total}")
        owners_count = db_row_count("petroleum_owner_catalog", "1=1", ())
        rep.check("petroleum_owner_catalog total == 1",
                  owners_count == 1, f"got {owners_count}")
        # 3 seed + 1 nuevo = 4
        doctypes_count = db_row_count("petroleum_doc_types", "1=1", ())
        rep.check("petroleum_doc_types total == 4 (3 seed + 1 nuevo)",
                  doctypes_count == 4, f"got {doctypes_count}")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

"""Bloque E · Vencimientos y alertas (cap. 3.3 de la propuesta)

Verifica el flujo completo de control de vencimientos:

* Crear normativa con fecha próxima → aparece automáticamente en
  ``document_deadlines`` (vía ``sync_document_deadlines``).
* Listado paginado / filtrado por urgencia, estación y módulo.
* KPIs (summary) reportan los conteos correctos por bucket de urgencia.
* Quick win #1: el default de ``reminder_days`` ahora es
  ``'60,30,15,7,3,1,0'``. Filas viejas se bumpean por trigger.
* Renew endpoint: actualiza la fecha, crea entrada en
  ``document_renewal_history``, valida formato y permisos.
* Calendar endpoint devuelve eventos en el rango.
* Export CSV genera headers correctos.
* Jefe de estación sólo ve deadlines de su(s) estación(es).

Como las normativas están hardcodeadas a ``brand='petroleum'`` en el
endpoint POST, este bloque trabaja casi exclusivamente con la estación
petroleum baseline + extras del mismo brand.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    db_get,
    login,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


def days_from_today(n: int) -> str:
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def insert_extra_station(brand: str, code: str, name: str, group_name: str | None = None) -> int:
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name) VALUES (?,?,?,?,?)",
        (brand, name, code, code, group_name),
    )
    sid = int(cur.lastrowid)
    conn.commit(); conn.close()
    return sid


def set_session_brand(env, brand: str) -> None:
    with env.client.session_transaction() as s:
        s["brand"] = brand


def main() -> int:
    rep = TestReporter("Bloque E · Vencimientos y alertas")
    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)
        sid_pet = baseline.station_petroleum_id

        # Operar siempre en marca petroleum para este bloque
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")

        # ====== 1. Crear 4 normativas con fechas en distintos buckets =======
        rep.section("Crear normativas con fechas para distintos buckets de urgencia")
        # Definir normativas (titulo, días hasta vencer) para 4 buckets:
        # vencido (-10), critico (+5), proximo (+20), programado (+60)
        normativas = [
            ("Bita NOM-005 vencida",   -10, "vencido"),
            ("Inspección anual",         5, "critico"),
            ("Calibración trimestral",  20, "proximo"),
            ("Auditoría anual",         60, "programado"),
        ]
        created_ids: list[int] = []
        for title, offset, _bucket in normativas:
            resp = env.client.post("/api/normativas", json={
                "station_id": sid_pet,
                "norma_title": title,
                "category": "Seguridad",
                "description": f"Test {title}",
                "periodicity": "anual",
                "compliance_date": days_from_today(offset - 365),
                "next_due_date": days_from_today(offset),
                "status": "en_proceso",
                "risk_level": "medio",
            })
            rep.check(f"normativa '{title}' creada → 200",
                      resp.status_code == 200, f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
            body = resp.get_json() or {}
            # POST normativa devuelve {ok, id}? Let's just check ok=True
            rep.check(f"respuesta ok=True para '{title}'",
                      body.get("ok") is True)

        # Recuperar los ids
        from db import get_conn
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, next_due_date, reminder_days FROM normativas WHERE brand='petroleum' ORDER BY id")
        normativa_rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        rep.check("se crearon 4 normativas en petroleum",
                  len(normativa_rows) == 4, f"got {len(normativa_rows)}")

        # ====== 2. Quick win #1: default reminder_days es '60,...' ==========
        rep.section("Quick win #1: nuevas normativas usan default '60,30,15,7,3,1,0'")
        all_ok = all(r.get("reminder_days") == "60,30,15,7,3,1,0" for r in normativa_rows)
        rep.check("las 4 normativas tienen reminder_days '60,30,15,7,3,1,0'",
                  all_ok,
                  f"got reminder_days={[r.get('reminder_days') for r in normativa_rows]}")

        # ====== 3. Trigger bumpea legacy '30,15,...' a 60d ==================
        rep.section("Trigger bumpea reminder_days legacy a 60d en INSERTs sin valor")
        conn = get_conn(); cur = conn.cursor()
        # Insertar normativa con reminder_days='30,15,7,3,1,0' (default viejo)
        # Para reproducir lo que pasaría si una BD vieja se reinicia con código nuevo.
        cur.execute(
            "INSERT INTO normativas (brand, station_id, norma_title, category, periodicity, "
            "compliance_date, next_due_date, status, risk_level, reminder_days) "
            "VALUES ('petroleum',?,?,?,?,?,?,?,?,?)",
            (sid_pet, "Legacy default", "Otra", "anual",
             days_from_today(-365), days_from_today(45),
             "en_proceso", "medio", "30,15,7,3,1,0"),
        )
        legacy_id = int(cur.lastrowid)
        conn.commit()
        # Verificar que el trigger lo bumpó
        cur.execute("SELECT reminder_days FROM normativas WHERE id=?", (legacy_id,))
        bumped = cur.fetchone()
        conn.close()
        rep.check("INSERT con default legacy '30,15,7,3,1,0' → bumpeado a 60d",
                  (bumped or {})["reminder_days"] == "60,30,15,7,3,1,0",
                  f"got {(bumped or {})['reminder_days']!r}")

        # Verificar también que un valor PERSONALIZADO se respeta (no se bumpea)
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO normativas (brand, station_id, norma_title, category, periodicity, "
            "compliance_date, next_due_date, status, risk_level, reminder_days) "
            "VALUES ('petroleum',?,?,?,?,?,?,?,?,?)",
            (sid_pet, "Custom reminder", "Otra", "anual",
             days_from_today(-365), days_from_today(45),
             "en_proceso", "medio", "90,30,7"),
        )
        custom_id = int(cur.lastrowid)
        conn.commit()
        cur.execute("SELECT reminder_days FROM normativas WHERE id=?", (custom_id,))
        custom = cur.fetchone()
        conn.close()
        rep.check("reminder_days personalizado '90,30,7' NO se sobrescribe",
                  (custom or {})["reminder_days"] == "90,30,7",
                  f"got {(custom or {})['reminder_days']!r}")

        # ====== 4. GET /api/document-deadlines lista las normativas =========
        rep.section("/api/document-deadlines lista las normativas creadas")
        resp = env.client.get("/api/document-deadlines")
        rep.check("admin → /api/document-deadlines → 200",
                  resp.status_code == 200)
        body = resp.get_json() or {}
        rows = body.get("rows") or []
        summary = body.get("summary") or {}
        rep.check("rows incluye al menos las 6 normativas creadas",
                  len(rows) >= 6, f"got {len(rows)}")
        titles = {(r.get("title") or "") for r in rows}
        for title, _, _ in normativas:
            rep.check(f"deadline '{title}' presente",
                      title in titles, f"got titles={titles}")

        # ====== 5. KPIs summary reflejan los buckets de urgencia ============
        rep.section("Summary refleja buckets de urgencia correctamente")
        urgencies = {(r.get("title"), r.get("urgency")) for r in rows}
        # Las 4 normativas controladas:
        for title, _offset, expected_bucket in normativas:
            actual = next((u for (t, u) in urgencies if t == title), None)
            rep.check(f"'{title}' tiene urgency='{expected_bucket}'",
                      actual == expected_bucket,
                      f"got urgency={actual!r}")

        rep.check("summary['total'] coincide con len(rows)",
                  summary.get("total") == len(rows),
                  f"summary={summary}")

        # ====== 6. Filtrar por urgencia ====================================
        rep.section("Filtros por urgencia")
        resp = env.client.get("/api/document-deadlines?urgency=vencido")
        rows_v = (resp.get_json() or {}).get("rows") or []
        only_vencidos = all(r.get("urgency") == "vencido" for r in rows_v)
        rep.check("urgency=vencido → solo rows con urgency='vencido'",
                  only_vencidos and len(rows_v) >= 1,
                  f"got {len(rows_v)} rows")

        resp = env.client.get("/api/document-deadlines?urgency=programado")
        rows_p = (resp.get_json() or {}).get("rows") or []
        only_programados = all(r.get("urgency") == "programado" for r in rows_p)
        rep.check("urgency=programado → solo rows con urgency='programado'",
                  only_programados and len(rows_p) >= 1,
                  f"got {len(rows_p)} rows")

        # ====== 7. Renovar deadline ========================================
        rep.section("Renovar deadline actualiza fecha y registra history")
        # Tomar el deadline correspondiente a la primera normativa
        target_deadline = next((r for r in rows if r.get("title") == "Inspección anual"), None)
        rep.check("encontrado deadline para 'Inspección anual'",
                  target_deadline is not None)
        deadline_id = (target_deadline or {}).get("id")
        old_due = (target_deadline or {}).get("due_date")
        new_due = days_from_today(180)

        resp = env.client.post(f"/api/document-deadlines/{deadline_id}/renew",
                                json={"new_due_date": new_due, "notes": "renovación manual"})
        rep.check("POST /renew → 200", resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        item = body.get("item") or {}
        rep.check("respuesta ok=True", body.get("ok") is True)

        # Verificar en BD que la normativa original se actualizó
        nrow = db_get("normativas", "norma_title=? AND brand='petroleum'", ("Inspección anual",))
        rep.check("normativa.next_due_date fue actualizada",
                  (nrow or {}).get("next_due_date") == new_due,
                  f"got {(nrow or {}).get('next_due_date')!r}")

        # Verificar history
        resp = env.client.get(f"/api/document-deadlines/{deadline_id}/history")
        body = resp.get_json() or {}
        items = body.get("items") or []
        rep.check("history tiene al menos una entrada", len(items) >= 1)
        h0 = items[0] if items else {}
        rep.check("history.old_due_date == fecha original",
                  h0.get("old_due_date") == old_due,
                  f"old expected {old_due}, got {h0.get('old_due_date')}")
        rep.check("history.new_due_date == nueva fecha",
                  h0.get("new_due_date") == new_due)

        # ====== 8. Renew con fecha inválida → 400 ==========================
        rep.section("Renew con fecha inválida → 400")
        resp = env.client.post(f"/api/document-deadlines/{deadline_id}/renew",
                                json={"new_due_date": "no-es-fecha"})
        rep.check("renew con fecha inválida → 400",
                  resp.status_code == 400, f"got {resp.status_code}")
        body = resp.get_json() or {}
        rep.check("error='invalid_due_date'",
                  body.get("error") == "invalid_due_date")

        # ====== 9. Export CSV ==============================================
        rep.section("Export CSV de deadlines")
        resp = env.client.get("/api/document-deadlines/export.csv")
        rep.check("export.csv → 200", resp.status_code == 200)
        rep.check("content-type indica CSV",
                  "csv" in (resp.headers.get("Content-Type") or "").lower(),
                  f"got {resp.headers.get('Content-Type')!r}")
        rep.check("filename en Content-Disposition contiene 'control_maestro'",
                  "control_maestro" in (resp.headers.get("Content-Disposition") or ""),
                  f"got {resp.headers.get('Content-Disposition')!r}")
        csv_text = resp.get_data(as_text=True)
        rep.check("CSV contiene header 'Vence'",
                  "Vence" in csv_text.splitlines()[0],
                  f"first line: {csv_text.splitlines()[0]!r}")
        rep.check("CSV contiene al menos una fila con 'Inspección anual'",
                  any("Inspección anual" in line for line in csv_text.splitlines()),
                  f"got {len(csv_text.splitlines())} lines")

        # ====== 10. Calendar endpoint ======================================
        rep.section("/api/document-renewals-calendar devuelve eventos en rango")
        resp = env.client.get("/api/document-renewals-calendar")
        rep.check("calendar endpoint → 200", resp.status_code == 200)
        body = resp.get_json() or {}
        items = body.get("items") or []
        rep.check("calendar tiene 'from' y 'to' en respuesta",
                  bool(body.get("from")) and bool(body.get("to")))
        # Calendar default range = first day of month + 62 days. La normativa
        # 'critico' (+5d desde hoy) debe caer en el rango.
        critico_title = "Inspección anual"  # ya renovada, ahora +180d
        # Tras renovar, esta fecha está fuera del rango default. Mejor verificar
        # otra que NO renovamos:
        proximo_title = "Calibración trimestral"  # +20d, debe caer en default
        in_calendar = any(it.get("title") == proximo_title for it in items)
        rep.check(f"calendar incluye '{proximo_title}' (dentro del rango default)",
                  in_calendar,
                  f"got {len(items)} items, titles={ {it.get('title') for it in items} }")

        # Rango explícito amplio
        resp = env.client.get(
            f"/api/document-renewals-calendar?from={days_from_today(-30)}&to={days_from_today(365)}"
        )
        items_wide = (resp.get_json() or {}).get("items") or []
        rep.check("rango amplio incluye también las normativas vencidas y futuras",
                  len(items_wide) >= len(items),
                  f"wide={len(items_wide)}, default={len(items)}")

        # ====== 11. Jefe sólo ve deadlines de su estación ==================
        rep.section("Jefe sólo ve deadlines de su estación")
        # Crear otra estación petroleum y una normativa allí
        sid_other = insert_extra_station("petroleum", "P-OTRA", "Otra Petroleum", group_name="X")
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO normativas (brand, station_id, norma_title, category, periodicity, "
            "compliance_date, next_due_date, status, risk_level) "
            "VALUES ('petroleum',?,?,?,?,?,?,?,?)",
            (sid_other, "Norma de Otra estación", "Seguridad", "anual",
             days_from_today(-30), days_from_today(40), "en_proceso", "medio"),
        )
        conn.commit(); conn.close()

        # jefe_pet pertenece a la estación petroleum baseline (con group_name="Demo")
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")
        resp = env.client.get("/api/document-deadlines")
        rep.check("jefe_pet → /api/document-deadlines → 200",
                  resp.status_code == 200)
        rows = (resp.get_json() or {}).get("rows") or []
        station_ids_in_response = {r.get("station_id") for r in rows}
        rep.check("jefe_pet NO ve deadlines de la 'Otra' estación",
                  sid_other not in station_ids_in_response,
                  f"got station_ids={station_ids_in_response}")
        rep.check("jefe_pet SÍ ve deadlines de su estación",
                  sid_pet in station_ids_in_response,
                  f"got station_ids={station_ids_in_response}")

        # ====== 12. Renew rechazado para jefe sobre estación ajena =========
        rep.section("Jefe NO puede renovar deadline de otra estación")
        # Admin obtiene el deadline de la 'Otra' estación
        login(env, "admin", "admin123")
        set_session_brand(env, "petroleum")
        resp = env.client.get("/api/document-deadlines")
        rows_admin = (resp.get_json() or {}).get("rows") or []
        other_deadline = next((r for r in rows_admin
                                if r.get("station_id") == sid_other), None)
        rep.check("admin encuentra el deadline de la otra estación",
                  other_deadline is not None)

        if other_deadline:
            other_id = other_deadline.get("id")
            # Verificación previa: la fila SÍ existe en BD con brand=petroleum
            db_row = db_get("document_deadlines", "id=? AND brand=?", (other_id, "petroleum"))
            rep.check("DIAG: deadline existe en BD con brand=petroleum",
                      db_row is not None,
                      f"got row={db_row}")
            login(env, "jefe_pet", "jefe123")
            set_session_brand(env, "petroleum")
            # Verificar el brand activo justo antes del POST
            with env.client.session_transaction() as s:
                active_brand = s.get("brand")
            rep.check("DIAG: brand activo justo antes del POST",
                      active_brand == "petroleum",
                      f"got brand={active_brand!r}")
            resp = env.client.post(f"/api/document-deadlines/{other_id}/renew",
                                    json={"new_due_date": days_from_today(200)})
            rep.check("jefe_pet → renew estación ajena → 403",
                      resp.status_code == 403,
                      f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")

        # ====== 13. Export CSV solo admin ==================================
        rep.section("Export CSV solo permitido a admin")
        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")
        resp = env.client.get("/api/document-deadlines/export.csv")
        rep.check("jefe_pet → export.csv → 403",
                  resp.status_code == 403, f"got {resp.status_code}")

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

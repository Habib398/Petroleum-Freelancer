"""Bloque I · Permisos y aislamiento

Verifica que la sumatoria de mecanismos de seguridad del sistema (rol,
station_scope_ids, marca activa de sesión, CSRF) realmente aísla los datos
como debería:

* Marca: un admin en ``consulting`` no debe ver estaciones de ``petroleum``.
* Estación: un jefe/operador solo debe ver datos de su propia estación.
* Auditor: lectura global dentro de la marca activa, pero **no** escritura.
* Endpoints admin-only: rechazan a roles inferiores con 403.
* Bitácoras: operador solo ve las suyas; admin/auditor ven todas (hallazgo
  documentado: no filtran por marca activa).
* CSRF: cuando está activo, un POST sin token es rechazado con 403.

Se ejecuta como ``.venv/Scripts/python.exe scripts/tests/test_block_I_permisos.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    login,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


# ---------------------------------------------------------------------------
# Data setup helpers (insert directly via SQL — Block I is about reading
# back what's there, not about exercising the create endpoints).
# ---------------------------------------------------------------------------

def insert_extra_station(brand: str, code: str, name: str) -> int:
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number) VALUES (?,?,?,?)",
        (brand, name, code, code.replace("-", "_")),
    )
    sid = int(cur.lastrowid)
    conn.commit(); conn.close()
    return sid


def insert_bitacora(brand: str, station_id: int, ref_date: str, kind: str = "daily",
                     notes: str = "") -> int:
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO bitacoras (brand, station_id, kind, ref_date, notes) VALUES (?,?,?,?,?)",
        (brand, station_id, kind, ref_date, notes),
    )
    bid = int(cur.lastrowid)
    conn.commit(); conn.close()
    return bid


def set_session_brand(env, brand: str) -> None:
    with env.client.session_transaction() as s:
        s["brand"] = brand


def get_session_brand(env) -> str | None:
    with env.client.session_transaction() as s:
        return s.get("brand")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    rep = TestReporter("Bloque I · Permisos y aislamiento")

    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)

        # Datos extra para que las pruebas de aislamiento tengan más de
        # una fila por brand/estación.
        st_consulting_extra = insert_extra_station(
            "consulting", "C-EXTRA", "Estación Consulting Extra")
        st_petroleum_extra = insert_extra_station(
            "petroleum", "P-EXTRA", "Estación Petroleum Extra")

        # 3 bitácoras: 2 consulting (en estaciones distintas) + 1 petroleum
        b1 = insert_bitacora("consulting", baseline.station_consulting_id, "2026-05-01",
                              notes="bita consulting estación principal")
        b2 = insert_bitacora("consulting", st_consulting_extra, "2026-05-02",
                              notes="bita consulting estación extra")
        b3 = insert_bitacora("petroleum", baseline.station_petroleum_id, "2026-05-03",
                              notes="bita petroleum estación principal")

        # ====== 1. Aislamiento por marca en /api/stations ===================
        rep.section("Aislamiento por marca en /api/stations")
        login(env, "admin", "admin123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/stations")
        rep.check("admin en consulting → /api/stations devuelve 200",
                  resp.status_code == 200, f"got {resp.status_code}")
        items = (resp.get_json() or {}).get("stations") or []
        brands_seen = {it.get("brand") for it in items}
        rep.check("admin en consulting → solo ve estaciones brand=consulting",
                  brands_seen == {"consulting"},
                  f"got brands={brands_seen}, count={len(items)}")
        codes_seen = {it.get("code") for it in items}
        rep.check("admin en consulting → ve baseline + extra (≥2 estaciones)",
                  "C-DEMO-N" in codes_seen and "C-EXTRA" in codes_seen,
                  f"got codes={codes_seen}")

        set_session_brand(env, "petroleum")
        resp = env.client.get("/api/stations")
        items = (resp.get_json() or {}).get("stations") or []
        brands_seen = {it.get("brand") for it in items}
        rep.check("admin en petroleum → solo ve estaciones brand=petroleum",
                  brands_seen == {"petroleum"},
                  f"got brands={brands_seen}")

        # ====== 2. Station scoping para jefe/operador =======================
        rep.section("Station scoping: jefe/operador solo ven SU estación")
        login(env, "jefe_test", "jefe123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/stations")
        items = (resp.get_json() or {}).get("stations") or []
        ids_seen = {int(it.get("id")) for it in items}
        rep.check("jefe_test → /api/stations devuelve 1 fila",
                  len(items) == 1, f"got {len(items)} items: {ids_seen}")
        rep.check("jefe_test → la estación es la suya (consulting principal)",
                  ids_seen == {baseline.station_consulting_id},
                  f"expected {{{baseline.station_consulting_id}}}, got {ids_seen}")

        login(env, "operador_test", "operador123")
        resp = env.client.get("/api/stations")
        items = (resp.get_json() or {}).get("stations") or []
        ids_seen = {int(it.get("id")) for it in items}
        rep.check("operador_test → /api/stations también restringido a su estación",
                  ids_seen == {baseline.station_consulting_id},
                  f"got ids={ids_seen}")

        # ====== 3. Auditor: alcance global dentro de su marca ==============
        rep.section("Auditor: alcance global dentro de marca activa")
        login(env, "auditor_test", "auditor123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/stations")
        items = (resp.get_json() or {}).get("stations") or []
        codes_seen = {it.get("code") for it in items}
        rep.check("auditor en consulting → ve TODAS las estaciones consulting (≥2)",
                  "C-DEMO-N" in codes_seen and "C-EXTRA" in codes_seen,
                  f"got codes={codes_seen}")
        rep.check("auditor en consulting → NO ve estaciones petroleum",
                  "P-DEMO" not in codes_seen and "P-EXTRA" not in codes_seen,
                  f"got codes={codes_seen}")

        # ====== 4. Endpoints admin-only rechazan no-admin ==================
        rep.section("Endpoints admin-only: 403 para roles inferiores")
        for username, password in (("jefe_test", "jefe123"),
                                    ("operador_test", "operador123"),
                                    ("auditor_test", "auditor123")):
            login(env, username, password)
            # /api/normativas GET es admin-only
            resp = env.client.get("/api/normativas")
            rep.check(f"{username} → GET /api/normativas devuelve 403",
                      resp.status_code == 403, f"got {resp.status_code}")
            # /api/users GET admin-only
            resp = env.client.get("/api/users")
            rep.check(f"{username} → GET /api/users devuelve 403",
                      resp.status_code == 403, f"got {resp.status_code}")
            # /api/admin/audit GET admin-only
            resp = env.client.get("/api/admin/audit")
            rep.check(f"{username} → GET /api/admin/audit devuelve 403",
                      resp.status_code == 403, f"got {resp.status_code}")

        # ====== 5. Auditor lectura OK (sí puede leer endpoints permitidos) ==
        rep.section("Auditor sí puede leer endpoints que NO son admin-only")
        login(env, "auditor_test", "auditor123")
        set_session_brand(env, "consulting")
        # /api/me siempre permitido si está logueado
        resp = env.client.get("/api/me")
        rep.check("auditor → /api/me → 200", resp.status_code == 200)
        # /api/bitacoras admite cualquier autenticado
        resp = env.client.get("/api/bitacoras")
        rep.check("auditor → /api/bitacoras → 200", resp.status_code == 200)
        # /api/document-deadlines
        resp = env.client.get("/api/document-deadlines")
        rep.check("auditor → /api/document-deadlines → 200",
                  resp.status_code == 200,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")

        # ====== 6. Bitácoras: operador solo ve las suyas ====================
        rep.section("Bitácoras: operador solo ve las de su estación")
        login(env, "operador_test", "operador123")
        resp = env.client.get("/api/bitacoras")
        rep.check("operador → /api/bitacoras → 200", resp.status_code == 200)
        items = (resp.get_json() or {}).get("bitacoras") or []
        ids_seen = {int(it["id"]) for it in items}
        rep.check("operador NO ve bitácora de otra estación consulting",
                  b2 not in ids_seen,
                  f"got ids={ids_seen}, b2={b2}")
        rep.check("operador NO ve bitácora de estación petroleum",
                  b3 not in ids_seen,
                  f"got ids={ids_seen}, b3={b3}")
        rep.check("operador SÍ ve la bitácora de su estación",
                  b1 in ids_seen,
                  f"got ids={ids_seen}, b1={b1}")

        # ====== 7. Hallazgo del sistema: admin/auditor en /api/bitacoras
        # NO filtran por marca activa (ven todas las marcas). Lo documentamos.
        rep.section("Hallazgo: /api/bitacoras NO filtra por marca activa (admin/auditor)")
        login(env, "admin", "admin123")
        set_session_brand(env, "consulting")
        resp = env.client.get("/api/bitacoras")
        items = (resp.get_json() or {}).get("bitacoras") or []
        ids_seen = {int(it["id"]) for it in items}
        rep.check("admin en consulting ve bitácora petroleum (b3) — comportamiento actual",
                  b3 in ids_seen,
                  f"got ids={ids_seen}; if b3 missing, filtering improved!")
        # Si esto pasa, está documentando que SI hay leak entre marcas.
        # Si en el futuro arreglan ese leak, este check pasaría de OK a FAIL y
        # nos avisaría que cambió el comportamiento.

        # ====== 8. Cross-station: jefe NO puede operar otra estación ========
        # /api/compliance/item/<code>/status valida que el usuario tenga acceso
        # a la estación. Sembramos un compliance_item primero (no viene en el
        # seed por defecto de init_db) para que el endpoint pase del 404 al
        # check de permisos.
        rep.section("Cross-station: jefe NO puede tocar otra estación")
        from db import get_conn as _conn
        _c = _conn(); _cu = _c.cursor()
        _cu.execute(
            "INSERT OR IGNORE INTO compliance_items (code, title, section, sort_order) "
            "VALUES ('nom005', 'NOM-005', 'Cumplimiento', 10)"
        )
        _c.commit(); _c.close()

        login(env, "jefe_pet", "jefe123")
        set_session_brand(env, "petroleum")
        resp = env.client.post(
            "/api/compliance/item/nom005/status",
            json={"station_id": st_petroleum_extra, "status": "approved"},
        )
        # st_petroleum_extra es de petroleum pero no es la estación del jefe_pet
        # y no comparte group_name → debe rechazar con 403 forbidden.
        rep.check("jefe_pet → POST a estación ajena devuelve 403",
                  resp.status_code == 403,
                  f"got {resp.status_code} body={resp.get_data(as_text=True)[:300]}")

        # ====== 9. CSRF: POST sin token rechazado cuando está activo ========
        # Importante: el login también es POST y requiere CSRF cuando está activo.
        # Por eso hacemos el login ANTES de activar CSRF, y luego cargamos el
        # token de la session.
        rep.section("CSRF: POST sin token devuelve 403 cuando CSRF está activo")
        rep.check("admin inicia sesión antes de activar CSRF",
                  login(env, "admin", "admin123"))
        # Disparar una request GET para asegurar que session.csrf_token quede
        # poblado por el before_request hook.
        env.client.get("/api/me")
        with env.client.session_transaction() as s:
            csrf_token = s.get("csrf_token")
        rep.check("session.csrf_token está poblado tras login",
                  bool(csrf_token))

        # Ahora activamos CSRF y probamos sin token
        os.environ["COG_CSRF"] = "1"
        try:
            resp = env.client.post(
                "/api/stations",
                json={"name": "Test CSRF", "code": "CSRF-1"},
            )
            rep.check("POST sin X-CSRF-Token → 403",
                      resp.status_code == 403,
                      f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")
            body = resp.get_json() or {}
            rep.check("respuesta tiene error='csrf'",
                      body.get("error") == "csrf",
                      f"got body={body}")

            # POST con token correcto: debe pasar
            resp = env.client.post(
                "/api/stations",
                json={"name": "Test CSRF OK", "code": "CSRF-2"},
                headers={"X-CSRF-Token": csrf_token or ""},
            )
            rep.check("POST con X-CSRF-Token válido → 200",
                      resp.status_code == 200,
                      f"got {resp.status_code} body={resp.get_data(as_text=True)[:200]}")

            # POST con token INCORRECTO también debe ser rechazado
            resp = env.client.post(
                "/api/stations",
                json={"name": "Test CSRF Bad", "code": "CSRF-3"},
                headers={"X-CSRF-Token": "token-falso-12345"},
            )
            rep.check("POST con X-CSRF-Token inválido → 403",
                      resp.status_code == 403,
                      f"got {resp.status_code}")
            body = resp.get_json() or {}
            rep.check("respuesta de token inválido tiene error='csrf'",
                      body.get("error") == "csrf",
                      f"got body={body}")
        finally:
            # Restaurar CSRF off para no contaminar bloques futuros
            os.environ["COG_CSRF"] = "0"

    finally:
        env.cleanup()

    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

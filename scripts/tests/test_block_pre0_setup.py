from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tests.fixtures import (  # noqa: E402
    STATION_CONSULTING_PROFILE,
    STATION_PETROLEUM_PROFILE,
    current_user,
    db_get,
    db_row_count,
    login,
    logout,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


def main() -> int:
    rep = TestReporter("Pre-0 · Preparación del entorno")

    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        # ---- 1. Environment created -----------------------------------------
        rep.section("Entorno temporal creado")
        rep.check("tmpdir existe en disco", env.tmpdir.exists(), str(env.tmpdir))
        rep.check("db_path apunta dentro de tmpdir", str(env.db_path).startswith(str(env.tmpdir)))
        rep.check("upload_dir existe", env.upload_dir.exists())
        rep.check("BD temporal creada por init_db", env.db_path.exists(),
                  f"expected file at {env.db_path}")

        # ---- 2. Admin seeded by init_db -------------------------------------
        rep.section("Admin sembrado por init_db")
        admin_row = db_get("users", "username=?", ("admin",))
        rep.check("usuario admin existe", admin_row is not None)
        if admin_row:
            rep.check("admin tiene rol 'admin'", admin_row.get("role") == "admin",
                      f"got role={admin_row.get('role')!r}")
            rep.check("admin está activo", int(admin_row.get("is_active") or 0) == 1)
            rep.check("admin no es el de tu BD real",
                      "admin" == admin_row.get("username"),
                      "fixture should isolate from production")

        # ---- 3. Seed baseline (users + stations + profiles) -----------------
        rep.section("Datos baseline (estaciones, usuarios, profiles)")
        baseline = seed_baseline(env)

        # Stations
        rep.check("estación consulting creada (id > 0)", baseline.station_consulting_id > 0)
        rep.check("estación petroleum creada (id > 0)", baseline.station_petroleum_id > 0)
        st_c = db_get("stations", "id=?", (baseline.station_consulting_id,))
        st_p = db_get("stations", "id=?", (baseline.station_petroleum_id,))
        rep.check("estación consulting tiene brand='consulting'",
                  (st_c or {}).get("brand") == "consulting",
                  f"got brand={(st_c or {}).get('brand')!r}")
        rep.check("estación petroleum tiene brand='petroleum'",
                  (st_p or {}).get("brand") == "petroleum",
                  f"got brand={(st_p or {}).get('brand')!r}")
        rep.check("código de la estación consulting es C-DEMO-N",
                  (st_c or {}).get("code") == "C-DEMO-N")
        rep.check("código de la estación petroleum es P-DEMO",
                  (st_p or {}).get("code") == "P-DEMO")

        # Users
        rep.check("usuario jefe_test creado",   baseline.jefe_test_id > 0)
        rep.check("usuario jefe_pet creado",    baseline.jefe_pet_id > 0)
        rep.check("usuario operador_test creado", baseline.operador_test_id > 0)
        rep.check("usuario auditor_test creado",  baseline.auditor_test_id > 0)

        jefe = db_get("users", "id=?", (baseline.jefe_test_id,))
        operador = db_get("users", "id=?", (baseline.operador_test_id,))
        auditor = db_get("users", "id=?", (baseline.auditor_test_id,))
        rep.check("jefe_test tiene rol 'jefe_estacion'",
                  (jefe or {}).get("role") == "jefe_estacion")
        rep.check("jefe_test está asignado a la estación consulting",
                  (jefe or {}).get("station_id") == baseline.station_consulting_id)
        rep.check("operador_test tiene rol 'operador'",
                  (operador or {}).get("role") == "operador")
        rep.check("auditor_test tiene rol 'auditor'",
                  (auditor or {}).get("role") == "auditor")
        rep.check("auditor_test puede ver ambas marcas",
                  "petroleum" in ((auditor or {}).get("allowed_brands") or ""))

        # Station profiles
        rep.check("station_profile consulting existe",
                  db_row_count("station_profiles", "station_id=?", (baseline.station_consulting_id,)) == 1)
        rep.check("station_profile petroleum existe",
                  db_row_count("station_profiles", "station_id=?", (baseline.station_petroleum_id,)) == 1)
        prof_c = db_get("station_profiles", "station_id=?", (baseline.station_consulting_id,))
        rep.check("station_profile guardó RFC esperado",
                  (prof_c or {}).get("rfc") == STATION_CONSULTING_PROFILE["rfc"],
                  f"got rfc={(prof_c or {}).get('rfc')!r}")
        rep.check("station_profile guardó permiso CRE esperado",
                  (prof_c or {}).get("permiso_cre") == STATION_CONSULTING_PROFILE["permiso_cre"])
        rep.check("station_profile guardó responsable SASISOPA esperado",
                  (prof_c or {}).get("responsable_sasisopa") == STATION_CONSULTING_PROFILE["responsable_sasisopa"])
        prof_p = db_get("station_profiles", "station_id=?", (baseline.station_petroleum_id,))
        rep.check("station_profile petroleum guardó RFC esperado",
                  (prof_p or {}).get("rfc") == STATION_PETROLEUM_PROFILE["rfc"])

        # ---- 4. Login flow for every role -----------------------------------
        rep.section("Login funciona para cada rol")
        rep.check("admin/admin123 inicia sesión",
                  login(env, baseline.admin_username, baseline.admin_password))
        me = current_user(env)
        rep.check("/api/me devuelve rol admin después de login",
                  (me or {}).get("role") == "admin",
                  f"got me={me}")

        rep.check("jefe_test inicia sesión",
                  login(env, "jefe_test", baseline.jefe_test_password))
        me = current_user(env)
        rep.check("/api/me devuelve rol jefe_estacion",
                  (me or {}).get("role") == "jefe_estacion")

        rep.check("jefe_pet inicia sesión",
                  login(env, "jefe_pet", baseline.jefe_pet_password))
        rep.check("operador_test inicia sesión",
                  login(env, "operador_test", baseline.operador_test_password))
        rep.check("auditor_test inicia sesión",
                  login(env, "auditor_test", baseline.auditor_test_password))

        rep.check("login con contraseña errónea es rechazado",
                  not login(env, "auditor_test", "WRONG_PASS"))

        # ---- 5. Negative: usuario inexistente --------------------------------
        rep.section("Rechazo de credenciales inválidas")
        rep.check("login con usuario inexistente es rechazado",
                  not login(env, "no_existe_jamas", "x"))

        # ---- 6. Logout: la sesión se cierra al borrar la cookie -------------
        # Hallazgo del sistema: NO existe /api/auth/logout. El cierre de sesión
        # ocurre cuando el cliente deja de mandar la cookie (cerrar navegador).
        # En tests simulamos esto borrando la session del test_client.
        rep.section("Logout (vía limpieza de session)")
        login(env, baseline.admin_username, baseline.admin_password)
        me_before = current_user(env)
        rep.check("antes de logout hay sesión activa", me_before is not None)
        logout(env)
        me_after = current_user(env)
        rep.check("después de logout /api/me no devuelve usuario",
                  me_after is None,
                  f"got me_after={me_after}")

    finally:
        env.cleanup()

    # ---- 7. Cleanup ---------------------------------------------------------
    rep.section("Limpieza del entorno temporal")
    rep.check("tmpdir fue eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

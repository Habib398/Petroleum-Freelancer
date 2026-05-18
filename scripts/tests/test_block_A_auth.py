"""Bloque A · Autenticación y sesión

Cubre los escenarios A1-A5 del PLAN_DE_PRUEBAS.md más validaciones adicionales
descubiertas durante la auditoría: validación de entrada, usuario inactivo,
lockout por contraseñas erróneas, rate limit por IP, decoradores
``@login_required`` y ``@role_required``, persistencia de sesión y cambio de
marca al acceder a URLs de Petroleum.

Notas sobre interacciones entre features:

* El **lockout por usuario** (5 fallos consecutivos → bloqueo 15 min) usa un
  usuario sacrificable creado dentro del test, para no inutilizar los users
  de la baseline.
* El **rate limit por IP** (8 fallos en 10 min → 429) limpia su bucket de
  memoria al inicio de cada sección que hace logins fallidos. Es la única
  forma fiable de hacer múltiples secciones sin estorbo cruzado.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from werkzeug.security import generate_password_hash  # noqa: E402

from scripts.tests.fixtures import (  # noqa: E402
    current_user,
    db_get,
    login,
    logout,
    make_test_env,
    seed_baseline,
)
from scripts.tests.reporter import TestReporter  # noqa: E402


def _clear_rate_login(env) -> None:
    """Reset the in-memory IP rate-limit bucket between subsections.

    Without this, sections that do several failed logins would consume the
    8-attempt allowance and the next section's first failed login would be
    answered with 429 (rate_limited) instead of 401 (invalid_credentials).
    """
    bucket = env.app.extensions.get("rate_login")
    if isinstance(bucket, dict):
        bucket.clear()


def _insert_user(username: str, password: str, role: str, *, is_active: int = 1,
                 primary_brand: str = "consulting", allowed_brands: str | None = None,
                 station_id: int | None = None, locked_until: int | None = None,
                 failed_attempts: int = 0) -> int:
    """Insert a user directly via SQL and return its id.

    Used to seed users with specific edge-case configurations (inactive,
    locked, etc.) that the fixtures' standard baseline doesn't cover.
    """
    from db import get_conn
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (brand, username, password_hash, role, primary_brand, "
        "allowed_brands, station_id, is_active, failed_attempts, locked_until) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            primary_brand, username, generate_password_hash(password), role,
            primary_brand, allowed_brands or primary_brand, station_id,
            int(is_active), int(failed_attempts), locked_until,
        ),
    )
    new_id = int(cur.lastrowid)
    conn.commit(); conn.close()
    return new_id


def main() -> int:
    rep = TestReporter("Bloque A · Autenticación y sesión")

    env = make_test_env()
    cleanup_path = env.tmpdir
    try:
        baseline = seed_baseline(env)

        # ====== 1. Login básico para cada rol ===============================
        rep.section("Login básico para cada rol (A1)")
        _clear_rate_login(env)
        rep.check("admin inicia sesión",        login(env, "admin", "admin123"))
        rep.check("jefe_test inicia sesión",    login(env, "jefe_test", "jefe123"))
        rep.check("jefe_pet inicia sesión",     login(env, "jefe_pet", "jefe123"))
        rep.check("operador_test inicia sesión",login(env, "operador_test", "operador123"))
        rep.check("auditor_test inicia sesión", login(env, "auditor_test", "auditor123"))

        # ====== 2. Validación de entrada ====================================
        rep.section("Validación de entrada en /api/auth/login")
        _clear_rate_login(env)
        logout(env)

        resp = env.client.post("/api/auth/login", json={"username": "", "password": ""})
        rep.check("campos vacíos → 401 invalid_credentials",
                  resp.status_code == 401,
                  f"got status={resp.status_code} body={resp.get_data(as_text=True)[:200]}")

        resp = env.client.post("/api/auth/login", json={"username": "admin"})
        rep.check("falta password → 401",
                  resp.status_code == 401,
                  f"got status={resp.status_code}")

        resp = env.client.post("/api/auth/login", data="{not json}",
                               content_type="application/json")
        rep.check("JSON malformado se maneja sin crash (≠ 500)",
                  resp.status_code != 500,
                  f"got status={resp.status_code}")

        # ====== 3. Credenciales inválidas (A2) ==============================
        rep.section("Credenciales inválidas (A2)")
        _clear_rate_login(env)
        rep.check("contraseña incorrecta → false",
                  not login(env, "admin", "wrong-password"))
        rep.check("usuario inexistente → false",
                  not login(env, "nadie", "x"))

        # Verificar el código de error específico
        resp = env.client.post("/api/auth/login",
                               json={"username": "admin", "password": "wrong"})
        body = resp.get_json() or {}
        rep.check("respuesta tiene error='invalid_credentials'",
                  body.get("error") == "invalid_credentials",
                  f"got body={body}")

        # ====== 4. Usuario inactivo =========================================
        rep.section("Usuario inactivo (is_active=0)")
        _clear_rate_login(env)
        _insert_user("inactivo_test", "x123", "operador", is_active=0,
                     station_id=baseline.station_consulting_id)
        resp = env.client.post("/api/auth/login",
                               json={"username": "inactivo_test", "password": "x123"})
        rep.check("usuario inactivo → 403 user_inactive",
                  resp.status_code == 403,
                  f"got status={resp.status_code}")
        body = resp.get_json() or {}
        rep.check("error='user_inactive'",
                  body.get("error") == "user_inactive",
                  f"got body={body}")

        # ====== 5. Lockout por contraseñas erróneas =========================
        # Política por defecto: 5 fallos consecutivos → bloqueo 15 min.
        rep.section("Lockout por intentos fallidos (5 fallos → user_locked)")
        _clear_rate_login(env)
        target_id = _insert_user("lockout_target", "secret999", "operador",
                                 station_id=baseline.station_consulting_id)

        for attempt in range(1, 6):
            resp = env.client.post("/api/auth/login",
                                   json={"username": "lockout_target", "password": "WRONG"})
            # Limpiar bucket entre intentos para que la respuesta sea
            # invalid_credentials y no rate_limited.
            _clear_rate_login(env)
        # En el 5° fallo el usuario queda lockeado. Siguiente intento devuelve 423.
        resp = env.client.post("/api/auth/login",
                               json={"username": "lockout_target", "password": "WRONG"})
        rep.check("tras 5 fallos, siguiente intento → 423 user_locked",
                  resp.status_code == 423,
                  f"got status={resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        # Incluso con contraseña correcta, sigue bloqueado.
        resp = env.client.post("/api/auth/login",
                               json={"username": "lockout_target", "password": "secret999"})
        rep.check("contraseña correcta no desbloquea (sigue 423)",
                  resp.status_code == 423,
                  f"got status={resp.status_code}")
        # Verificar que el campo locked_until quedó poblado en BD
        u = db_get("users", "id=?", (target_id,))
        rep.check("BD tiene locked_until > 0 para el usuario",
                  int((u or {}).get("locked_until") or 0) > 0,
                  f"got user={u}")

        # ====== 6. Rate limit por IP (A3) ===================================
        # Política: 8 fallos por IP en 10 min → 429.
        # Usamos un username inexistente para no lockear a ningún usuario real.
        rep.section("Rate limit por IP (A3) — 8 fallos → 429")
        _clear_rate_login(env)
        # 8 intentos: deberían responder 401 invalid_credentials
        statuses = []
        for i in range(8):
            resp = env.client.post("/api/auth/login",
                                   json={"username": f"nobody_{i}", "password": "x"})
            statuses.append(resp.status_code)
        rep.check("los primeros 8 intentos NO son rate-limited",
                  all(s == 401 for s in statuses),
                  f"got statuses={statuses}")
        # 9° intento → 429
        resp = env.client.post("/api/auth/login",
                               json={"username": "nobody_9", "password": "x"})
        rep.check("9° intento devuelve 429 rate_limited",
                  resp.status_code == 429,
                  f"got status={resp.status_code} body={resp.get_data(as_text=True)[:200]}")
        body = resp.get_json() or {}
        rep.check("error='rate_limited'",
                  body.get("error") == "rate_limited",
                  f"got body={body}")
        # Un login exitoso resetea el bucket.
        _clear_rate_login(env)  # garantizar limpieza para la siguiente sección

        # ====== 7. @login_required protege endpoints ========================
        rep.section("@login_required: endpoints requieren sesión activa")
        logout(env)
        resp = env.client.get("/api/me")
        rep.check("/api/me sin sesión → 401",
                  resp.status_code == 401,
                  f"got status={resp.status_code}")
        resp = env.client.get("/api/stations")
        rep.check("/api/stations sin sesión → 401",
                  resp.status_code == 401)
        resp = env.client.get("/api/notifications")
        rep.check("/api/notifications sin sesión → 401",
                  resp.status_code == 401)

        # ====== 8. @role_required: jefe no puede entrar a admin =============
        rep.section("@role_required: rol no admin → 403 en endpoints admin-only")
        rep.check("jefe_test inicia sesión", login(env, "jefe_test", "jefe123"))
        resp = env.client.get("/api/admin/audit")
        rep.check("jefe → /api/admin/audit → 403",
                  resp.status_code == 403,
                  f"got status={resp.status_code}")
        resp = env.client.get("/api/users")
        rep.check("jefe → /api/users → 403",
                  resp.status_code == 403,
                  f"got status={resp.status_code}")
        # Admin sí puede
        rep.check("admin inicia sesión", login(env, "admin", "admin123"))
        resp = env.client.get("/api/admin/audit")
        rep.check("admin → /api/admin/audit → 200",
                  resp.status_code == 200,
                  f"got status={resp.status_code}")

        # ====== 9. Persistencia de sesión ===================================
        rep.section("Persistencia de sesión entre requests")
        # admin sigue logueado de la sección anterior
        me1 = current_user(env)
        me2 = current_user(env)
        me3 = current_user(env)
        rep.check("/api/me devuelve el mismo usuario 3 veces seguidas",
                  me1 is not None and me2 is not None and me3 is not None
                  and me1.get("id") == me2.get("id") == me3.get("id"),
                  f"got ids={(me1 or {}).get('id')}, {(me2 or {}).get('id')}, {(me3 or {}).get('id')}")

        # ====== 10. Cambio de marca (A5) ====================================
        # Importante: la marca activa vive en session["brand"], NO en me["brand"]
        # (este último es la marca-base del usuario en la tabla users). Por eso
        # leemos directamente la session del test_client en vez de /api/me.
        def session_brand() -> str | None:
            with env.client.session_transaction() as s:
                return s.get("brand")

        rep.section("Cambio de marca: admin → /petroleum activa marca petroleum (A5)")
        # Asegurar arranque limpio en consulting
        login(env, "admin", "admin123")
        with env.client.session_transaction() as s:
            s["brand"] = "consulting"
        rep.check("admin parte en consulting", session_brand() == "consulting",
                  f"got session brand={session_brand()!r}")

        # Hit a Petroleum URL — el middleware before_request debería activar la marca
        env.client.get("/petroleum", follow_redirects=False)
        rep.check("después de tocar /petroleum, session.brand=petroleum",
                  session_brand() == "petroleum",
                  f"got session brand={session_brand()!r}")

        # jefe_test (solo consulting) NO debe quedarse en petroleum.
        #
        # Hallazgo del sistema: la ruta /petroleum hace session['brand']='petroleum'
        # directamente sin validar allowed_brands del usuario. La protección real
        # vive en el middleware before_request: en la SIGUIENTE request detecta
        # que el brand activo no está permitido y lo regresa a 'consulting'.
        # Por eso ejercitamos /petroleum y luego una request normal antes de
        # verificar — replicando lo que pasa en un navegador real al navegar.
        rep.check("jefe_test inicia sesión", login(env, "jefe_test", "jefe123"))
        with env.client.session_transaction() as s:
            s["brand"] = "consulting"
        env.client.get("/petroleum", follow_redirects=False)
        # Siguiente request: el middleware enforces allowed_brands
        env.client.get("/api/me")
        rep.check("jefe_test fue regresado a consulting tras enforcement",
                  session_brand() == "consulting",
                  f"got session brand={session_brand()!r}")

    finally:
        env.cleanup()

    # ---- Cleanup --------------------------------------------------------
    rep.section("Limpieza")
    rep.check("tmpdir eliminado", not cleanup_path.exists(), str(cleanup_path))

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())

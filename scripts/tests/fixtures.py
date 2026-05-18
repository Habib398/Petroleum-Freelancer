"""Shared fixtures for the test-block scripts.

Every block script starts with the same prep: a throw-away SQLite database,
a temporary uploads directory, a Flask app pointed at them, a test_client,
and a baseline of users + stations so the assertions have something to act
on. This module centralizes all of that so each block stays focused on its
own scenarios.

Typical usage from a block script::

    from scripts.tests.fixtures import make_test_env, seed_baseline, login
    from scripts.tests.reporter import TestReporter

    rep = TestReporter("Bloque A — Autenticación")
    env = make_test_env()
    baseline = seed_baseline(env)
    try:
        rep.section("Login admin")
        rep.check("login returns 200", login(env, "admin", "admin123"))
        # ... more checks ...
    finally:
        env.cleanup()
    sys.exit(rep.summary())

The fixtures intentionally write directly to the DB rather than going through
the user-creation API. This isolates each test block from bugs in unrelated
endpoints: if creating a user is broken, the affected block (I — permisos)
discovers it through its own checks, not through fixture failure that breaks
every block at once.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Make the project root importable when these scripts are run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------

@dataclass
class TestEnv:
    """Holds everything a block script needs to run.

    The Flask ``app`` is freshly created on a temporary SQLite + uploads
    directory. ``client`` is the Flask test_client (no real network).
    Standard data created by :func:`seed_baseline` is later available
    through the :class:`Baseline` returned by that call.
    """
    app: object
    client: object
    tmpdir: Path
    db_path: Path
    upload_dir: Path
    _cleaned: bool = field(default=False, init=False)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        # Release SQLite connections still held by per-request objects so
        # Windows can drop the .db / .db-wal files. Without this GC pass the
        # rmtree below silently fails on Windows and leaves a stale tmpdir.
        import gc, time
        gc.collect()
        for _ in range(5):
            try:
                shutil.rmtree(self.tmpdir, ignore_errors=False)
                return
            except OSError:
                gc.collect()
                time.sleep(0.1)
        shutil.rmtree(self.tmpdir, ignore_errors=True)


@dataclass
class Baseline:
    """IDs and credentials for the data seeded by :func:`seed_baseline`.

    Block scripts dereference attributes here instead of hardcoding IDs,
    which keeps the fixtures portable if seed order changes later.
    """
    admin_id: int
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # Test users (consulting unless noted)
    jefe_test_id: int = 0
    jefe_test_password: str = "jefe123"
    jefe_pet_id: int = 0
    jefe_pet_password: str = "jefe123"
    operador_test_id: int = 0
    operador_test_password: str = "operador123"
    auditor_test_id: int = 0
    auditor_test_password: str = "auditor123"

    # Stations
    station_consulting_id: int = 0
    station_consulting_code: str = "C-DEMO-N"
    station_petroleum_id: int = 0
    station_petroleum_code: str = "P-DEMO"


def make_test_env() -> TestEnv:
    """Boot a fresh Flask app on a temp SQLite + uploads dir.

    The function pins all the environment variables the project reads at
    import time (``COG_DB_PATH``, ``COG_UPLOAD_DIR``, ``COG_CSRF``, etc.),
    then force-reloads any project modules that may have been cached from
    a previous run in the same Python process.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="worklog_tests_"))
    db_path = tmpdir / "test.db"
    upload_dir = tmpdir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    os.environ["COG_DB_PATH"] = str(db_path)
    os.environ["COG_UPLOAD_DIR"] = str(upload_dir)
    os.environ["COG_CSRF"] = "0"                  # bypass CSRF in test_client calls
    os.environ["COG_SECRET"] = "test-secret"
    os.environ["COG_ADMIN_USER"] = "admin"
    os.environ["COG_ADMIN_PASS"] = "admin123"
    os.environ["COG_RUNTIME_SCHEDULER"] = "0"     # don't fire background jobs
    os.environ["COG_DISABLE_BACKUP_TICK"] = "1"   # don't auto-backup during tests

    # Wipe any previously cached project modules so the new env vars take effect.
    for mod_name in list(sys.modules):
        if mod_name in {"db", "app"} or mod_name.startswith(("modules.", "services.")):
            del sys.modules[mod_name]

    app_module = importlib.import_module("app")
    app = app_module.create_app()
    app.testing = True
    client = app.test_client()

    return TestEnv(app=app, client=client, tmpdir=tmpdir, db_path=db_path, upload_dir=upload_dir)


# ---------------------------------------------------------------------------
# Baseline seed
# ---------------------------------------------------------------------------

# Realistic-looking station profile data so autofill tests have something
# substantive to read. Kept in module scope so tests can compare against it.
STATION_CONSULTING_PROFILE = {
    "permit_number":          "PER/001/2025",
    "legal_name":             "Demo Consulting S.A. de C.V.",
    "rfc":                    "DCO250101AB1",
    "domicilio":              "Av. Insurgentes 100, CDMX, CP 03100",
    "permiso_cre":            "PL/9001/EXP/ES/2026",
    "representante_legal":    "Lic. Ana Torres",
    "responsable_operativo":  "Ing. Luis Ramírez",
    "responsable_sasisopa":   "Ing. María Pérez",
    "responsable_sgm":        "Ing. José Hernández",
    "correo":                 "demo.norte@example.com",
    "telefono":               "55-1234-9001",
}

STATION_PETROLEUM_PROFILE = {
    "permit_number":          "PER/002/2025",
    "legal_name":             "Demo Petroleum S.A. de C.V.",
    "rfc":                    "DPE250101AB1",
    "domicilio":              "Carretera 145 km 12, Las Choapas, Ver.",
    "permiso_cre":            "PL/9002/EXP/ES/2026",
    "representante_legal":    "Lic. Carlos Mendoza",
    "responsable_operativo":  "Ing. Pedro Castillo",
    "responsable_sasisopa":   "Ing. Sofía Vega",
    "responsable_sgm":        "Ing. Roberto Díaz",
    "correo":                 "demo.pet@example.com",
    "telefono":               "921-5555-9002",
}


def seed_baseline(env: TestEnv) -> Baseline:
    """Insert the standard test users, stations and station_profiles.

    Returns a :class:`Baseline` with their IDs. Direct DB writes are used
    on purpose; see the module docstring for the rationale.
    """
    from db import get_conn
    from werkzeug.security import generate_password_hash

    conn = get_conn()
    cur = conn.cursor()

    admin_row = cur.execute(
        "SELECT id FROM users WHERE username='admin' LIMIT 1"
    ).fetchone()
    if not admin_row:
        raise RuntimeError("admin user not seeded by init_db")
    admin_id = int(admin_row["id"])

    # --- Stations (1 consulting, 1 petroleum) ---
    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name, state, city, address) "
        "VALUES ('consulting','Estación Demo Norte','C-DEMO-N','9001','Demo','CDMX','Iztapalapa','Av. Test 100')"
    )
    sid_consulting = int(cur.lastrowid)

    cur.execute(
        "INSERT INTO stations (brand, name, code, station_number, group_name, state, city, address) "
        "VALUES ('petroleum','Estación Demo Pet','P-DEMO','9002','Demo','Veracruz','Las Choapas','Carretera 145 km 12')"
    )
    sid_petroleum = int(cur.lastrowid)

    # --- Test users ---
    user_specs = [
        # (username, password, role, primary_brand, allowed_brands, station_id)
        ("jefe_test",     "jefe123",     "jefe_estacion", "consulting", "consulting",            sid_consulting),
        ("jefe_pet",      "jefe123",     "jefe_estacion", "petroleum",  "petroleum",             sid_petroleum),
        ("operador_test", "operador123", "operador",      "consulting", "consulting",            sid_consulting),
        ("auditor_test",  "auditor123",  "auditor",       "consulting", "consulting,petroleum",  None),
    ]
    user_ids: dict[str, int] = {}
    for username, password, role, prim, allowed, station_id in user_specs:
        cur.execute(
            "INSERT INTO users (brand, username, password_hash, role, primary_brand, allowed_brands, station_id, is_active) "
            "VALUES (?,?,?,?,?,?,?,1)",
            (prim, username, generate_password_hash(password), role, prim, allowed, station_id),
        )
        user_ids[username] = int(cur.lastrowid)

    # --- Station profiles (populates the rich private data added in quick wins) ---
    def _insert_profile(station_id: int, brand: str, data: dict) -> None:
        cur.execute(
            "INSERT INTO station_profiles ("
            "  station_id, brand, permit_number, legal_name, rfc, domicilio, permiso_cre, "
            "  representante_legal, responsable_operativo, responsable_sasisopa, responsable_sgm, "
            "  correo, telefono, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (
                station_id, brand,
                data["permit_number"], data["legal_name"], data["rfc"], data["domicilio"],
                data["permiso_cre"], data["representante_legal"], data["responsable_operativo"],
                data["responsable_sasisopa"], data["responsable_sgm"], data["correo"], data["telefono"],
            ),
        )

    _insert_profile(sid_consulting, "consulting", STATION_CONSULTING_PROFILE)
    _insert_profile(sid_petroleum,  "petroleum",  STATION_PETROLEUM_PROFILE)

    conn.commit()
    conn.close()

    return Baseline(
        admin_id=admin_id,
        jefe_test_id=user_ids["jefe_test"],
        jefe_pet_id=user_ids["jefe_pet"],
        operador_test_id=user_ids["operador_test"],
        auditor_test_id=user_ids["auditor_test"],
        station_consulting_id=sid_consulting,
        station_petroleum_id=sid_petroleum,
    )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login(env: TestEnv, username: str, password: str) -> bool:
    """Log a user in through ``/api/auth/login``.

    Returns ``True`` when the login endpoint reports ``ok=true``. Callers
    typically wrap this in :meth:`TestReporter.check` so a login failure
    shows up as a single labelled assertion.
    """
    resp = env.client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code != 200:
        return False
    body = resp.get_json(silent=True) or {}
    return body.get("ok") is True


def logout(env: TestEnv) -> None:
    """Clear the test_client session.

    The project does not expose an HTTP logout endpoint — sessions end when
    the cookie is removed. Tests simulate that by wiping the session storage
    directly, which is equivalent to the user closing their browser.
    """
    with env.client.session_transaction() as sess:
        sess.clear()


def current_user(env: TestEnv) -> dict | None:
    """Return the current user dict from ``/api/me``, or ``None`` if anonymous.

    ``/api/me`` wraps the user under a ``"me"`` key (``{"me": {...}}``), so
    this helper unwraps it for callers that only care about the user fields.
    """
    resp = env.client.get("/api/me")
    if resp.status_code != 200:
        return None
    body = resp.get_json(silent=True) or {}
    me = body.get("me") if isinstance(body, dict) else None
    if not isinstance(me, dict):
        return None
    return me


# ---------------------------------------------------------------------------
# DB convenience
# ---------------------------------------------------------------------------

def db_row_count(table: str, where: str = "1=1", params: tuple = ()) -> int:
    """Quick way to count rows in a table for an assertion."""
    from db import get_conn
    conn = get_conn()
    try:
        cur = conn.cursor()
        n = cur.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params).fetchone()
        return int(n["c"] if n else 0)
    finally:
        conn.close()


def db_get(table: str, where: str, params: tuple) -> dict | None:
    """Fetch one row as a dict, or ``None``."""
    from db import get_conn
    conn = get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1", params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

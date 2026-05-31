import atexit
import os, sqlite3
import re
from services.db_compat import build_postgres_connection, is_postgres_env
try:
    from services.brand import get_brand as _get_brand
except Exception:
    _get_brand = None

_REWRITE_PATTERNS = [
    (re.compile(r"\bactivities\b"), "agenda_activities"),
    (re.compile(r"\bcalendar_events\b"), "agenda_calendar_events"),
    (re.compile(r"\bsubmissions\b"), "agenda_submissions"),
]

def _safe_brand() -> str:
    # get_brand() uses Flask session; outside request it can raise.
    if _get_brand is None:
        return "consulting"
    try:
        return _get_brand()
    except Exception:
        return "consulting"

def _rewrite_sql(sql: str) -> str:
    # For Petroleum, map Activities/Calendar/Submissions to independent Agenda tables.
    if _safe_brand() != "petroleum":
        return sql
    out = sql
    for rx, repl in _REWRITE_PATTERNS:
        out = rx.sub(repl, out)
    return out

class BrandCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return super().execute(_rewrite_sql(sql), parameters)

    def executemany(self, sql, seq_of_parameters):
        return super().executemany(_rewrite_sql(sql), seq_of_parameters)

    def executescript(self, sql_script):
        # Do not rewrite schema scripts; keep base schema stable.
        return super().executescript(sql_script)

class BrandConnection(sqlite3.Connection):
    def cursor(self, factory=None):
        return super().cursor(factory or BrandCursor)

from werkzeug.security import generate_password_hash, check_password_hash


# -----------------------------------------------------------------------------
# Row factory
# -----------------------------------------------------------------------------
# The codebase uses both styles:
#   - row["col"] and row.get("col")
#   - row[0] for single-column queries
# sqlite3.Row supports name + index access, but it does not implement .get().
# We use a small dict-like wrapper that supports all three patterns.

class RowObj(dict):
    __slots__ = ("_cols",)

    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._cols = list(cols)

    def __getitem__(self, key):
        if isinstance(key, int):
            return super().__getitem__(self._cols[key])
        return super().__getitem__(key)

    def get(self, key, default=None):
        if isinstance(key, int):
            try:
                key = self._cols[key]
            except Exception:
                return default
        return super().get(key, default)


def row_factory(cursor, row):
    cols = [d[0] for d in (cursor.description or [])]
    return RowObj(cols, row)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("COG_DB_PATH") or os.path.join(BASE_DIR, "data", "cog_work_log.db")
DB_ENGINE = (os.environ.get("COG_DB_ENGINE") or ("postgres" if is_postgres_env() else "sqlite")).strip().lower()

# Shared-cache in-memory DB support for tests (kept alive by a keeper connection)
_MEM_KEEPER = None  # type: ignore

# In-memory DB support for tests (keep one connection alive)
_MEM_CONN = None  # type: ignore

def get_conn():
    """Return a DB connection in sqlite or postgres compatibility mode.

    PostgreSQL is enabled with COG_DB_ENGINE=postgres or a postgres:// DATABASE_URL.
    SQLite remains the default local fallback.
    """
    global _MEM_KEEPER
    if DB_ENGINE in {"postgres", "postgresql", "pg", "psycopg"} or is_postgres_env():
        return build_postgres_connection(rewrite_sql=_rewrite_sql)

    if DB_PATH == ":memory:":
        uri_path = "file:cog_memdb?mode=memory&cache=shared"
        if _MEM_KEEPER is None:
            _MEM_KEEPER = sqlite3.connect(uri_path, uri=True, timeout=10, factory=BrandConnection, check_same_thread=False)
            _MEM_KEEPER.row_factory = row_factory
            _MEM_KEEPER.execute("PRAGMA foreign_keys = ON;")
            try:
                _MEM_KEEPER.execute("PRAGMA busy_timeout = 5000;")
            except Exception:
                pass
        conn = sqlite3.connect(uri_path, uri=True, timeout=10, factory=BrandConnection, check_same_thread=False)
        conn.row_factory = row_factory
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            conn.execute("PRAGMA busy_timeout = 5000;")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA synchronous = NORMAL;")
        except Exception:
            pass
        return conn

    conn = sqlite3.connect(DB_PATH, timeout=10, factory=BrandConnection, check_same_thread=False)
    conn.row_factory = row_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA busy_timeout = 5000;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn

def _close_mem_connections():
    global _MEM_KEEPER, _MEM_CONN
    for attr in ("_MEM_KEEPER", "_MEM_CONN"):
        conn = globals().get(attr)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            globals()[attr] = None

atexit.register(_close_mem_connections)


def _table_columns(conn, table:str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}

def ensure_column(conn, table:str, column:str, ddl:str):
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")



def _ensure_column(conn, table: str, column: str, coldef: str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
        conn.commit()


# ---------------- versioned schema migrations (ISO-friendly) ----------------
def _ensure_schema_migrations(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "id TEXT PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "notes TEXT)"
    )
    conn.commit()

def _migration_applied(conn, mid: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM schema_migrations WHERE id=?", (mid,))
    return cur.fetchone() is not None

def _mark_migration(conn, mid: str, notes: str = "") -> None:
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO schema_migrations (id, notes) VALUES (?,?)", (mid, notes or ""))
    conn.commit()

def _safe_executescript(conn, script: str) -> None:
    try:
        conn.executescript(script)
        conn.commit()
    except Exception:
        # Ignore to keep init resilient; logs will show if running app
        pass

def _add_months_seed(d, months:int):
    import calendar as _cal
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, _cal.monthrange(y, m)[1])
    return d.replace(year=y, month=m, day=day)

def _dates_for_seed_frequency(year:int, freq:str):
    import datetime as _dt
    start = _dt.date(year, 1, 1)
    end = _dt.date(year, 12, 31)
    out = []
    if freq == 'daily':
        cur = start
        while cur <= end:
            out.append(cur)
            cur += _dt.timedelta(days=1)
        return out
    if freq == 'monthly':
        cur = start
        while cur <= end:
            out.append(cur)
            cur = _add_months_seed(cur, 1)
        return out
    if freq == 'quarterly':
        cur = start
        while cur <= end:
            out.append(cur)
            cur = _add_months_seed(cur, 3)
        return out
    if freq == 'fourmonthly':
        cur = start
        while cur <= end:
            out.append(cur)
            cur = _add_months_seed(cur, 4)
        return out
    if freq == 'semiannual':
        return [start, _dt.date(year, 7, 1)]
    if freq == 'yearly':
        return [start]
    if freq == 'fiveyearly':
        return [start]
    return [start]

def _detect_consulting_pm_anchor_year(conn, default_year:int|None=None) -> int:
    """Detect the anchor year for the preventive-maintenance program.

    We keep the 5-year cycle stable starting from the first seeded PM year,
    so future years are generated consistently instead of duplicating the
    five-year activity every single year.
    """
    import datetime as _dt
    default_year = int(default_year or _dt.date.today().year)
    cur = conn.cursor()
    cur.execute("SELECT title FROM activities WHERE brand='consulting' AND title LIKE '[PM20%' ORDER BY id ASC")
    years = []
    for row in cur.fetchall():
        try:
            title = row['title'] if isinstance(row, dict) else row[0]
            if title and title.startswith('[PM') and len(title) >= 8:
                years.append(int(title[3:7]))
        except Exception:
            continue
    return min(years) if years else default_year


def _pm_activity_items_for_year(year:int, anchor_year:int) -> list[tuple[str,int,str]]:
    items = [
        ('daily', 1, 'Limpieza general en áreas comunes, paredes, bardas, herrería, puertas, ventanas, señales y avisos.'),
        ('daily', 2, 'Limpieza general de sanitarios (empleados y públicos).'),
        ('daily', 3, 'Limpieza en el exterior de dispensarios.'),
        ('daily', 4, 'Limpieza de registros y trampa de grasas para retirar aceites y sólidos gruesos.'),
        ('monthly', 5, 'Revisar que las luminarias de toda la estación estén funcionando correctamente.'),
        ('monthly', 6, 'Detección de fugas y derrames (anexar inventarios y tickets de alarmas de sensores).'),
        ('monthly', 7, 'Lavado de pisos en áreas de despacho. Lavar con agua y desengrasante.'),
        ('monthly', 8, 'Limpieza en zona de almacenamiento. Lavar con agua y desengrasante.'),
        ('monthly', 9, 'Limpieza de registros y rejillas. Retirar rejillas y lavar con agua y desengrasante.'),
        ('monthly', 10, 'Realizar inspección y hacer limpieza de trampas de combustibles y de grasas; recolectar residuos flotantes y lodos en depósitos de cierre hermético.'),
        ('monthly', 11, 'Drenado de los tanques (sistema de control de inventario; anexar tickets).'),
        ('monthly', 12, 'Verificación del funcionamiento del sistema de control de inventario (imprimir inventario).'),
        ('monthly', 13, 'Limpieza e inspección de contenedores de bomba sumergible y accesorios / dispensario, sin fugas y con sellado hermético.'),
        ('monthly', 14, 'Revisión de tinacos o cisterna.'),
        ('monthly', 15, 'Revisión de paros de emergencia e interruptores de emergencia.'),
        ('monthly', 16, 'Limpieza de contenedores en bocatoma de llenado que estén libres de combustible y revisar que estén herméticos.'),
        ('quarterly', 17, 'Retiro de residuos peligrosos para su manejo y disposición final, generados en actividades de mantenimiento y limpieza, con empresas autorizadas.'),
        ('quarterly', 18, 'Revisión de los flotadores en el sistema de medición.'),
        ('fourmonthly', 19, 'Pintura en general (guarniciones, fachada de oficinas, señalamientos verticales y marcaje en pavimentos).'),
        ('fourmonthly', 20, 'Limpieza de faldones y anuncio independiente.'),
        ('semiannual', 21, 'Revisión de interruptores, contactos, cajas de conexiones, sellos eléctricos y tableros, verificando que tengan su correspondiente tapa.'),
        ('yearly', 22, 'Realizar pruebas de hermeticidad en tanques y tuberías.'),
        ('yearly', 23, 'Recalibración de tanques de almacenamiento.'),
        ('yearly', 24, 'Revisión de continuidad eléctrica del sistema.'),
        ('yearly', 25, 'Mantenimiento de extintores (según la norma NOM-002).'),
    ]
    if ((int(year) - int(anchor_year)) % 5) == 0:
        items.append(('fiveyearly', 26, 'Limpieza en el interior de tanques de almacenamiento (hacer por escrito autorización e indicar en la bitácora fecha de inicio y terminación).'))
    return items


def _seed_consulting_preloaded_activities(conn, year:int|None=None, *, anchor_year:int|None=None):
    """Precarga actividades base de Consulting para un año específico."""
    import datetime as _dt
    year = int(year or _dt.date.today().year)
    anchor_year = int(anchor_year or _detect_consulting_pm_anchor_year(conn, year))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM activities WHERE brand='consulting' AND title LIKE ?", (f"[PM{year}] #%",))
    row = cur.fetchone()
    try:
        exists = int(row['c'] or 0)
    except Exception:
        exists = int(row[0] or 0) if row else 0
    if exists > 0:
        return 0
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    row = cur.fetchone()
    created_by = row['id'] if row and isinstance(row, dict) else (row[0] if row else None)
    created = 0
    for freq, num, desc in _pm_activity_items_for_year(year, anchor_year):
        title = f"[PM{year}] #{num:02d} • {desc[:72]}"
        cur.execute(
            "INSERT INTO activities (brand, title, description, evidence_required, is_active, created_by, recurrence, target_station_id) VALUES (?,?,?,?,?,?,?,NULL)",
            ('consulting', title, desc, 1, 1, created_by, freq),
        )
        aid = cur.lastrowid
        for d in _dates_for_seed_frequency(year, freq):
            cur.execute(
                "INSERT INTO calendar_events (brand, activity_id, title, start_date, repeat_kind, station_id, created_by) VALUES (?,?,?,?,?,?,?)",
                ('consulting', aid, title, d.isoformat(), freq, None, created_by),
            )
            created += 1
    conn.commit()
    return created


def _seed_consulting_preloaded_activities_window(conn, start_year:int|None=None, years_ahead:int=5) -> int:
    """Keep Consulting PM activities preloaded for a rolling multi-year window.

    Example with current year 2026 and years_ahead=5:
    seeds 2026, 2027, 2028, 2029, 2030 and 2031.
    """
    import datetime as _dt
    start_year = int(start_year or _dt.date.today().year)
    years_ahead = max(0, int(years_ahead or 0))
    anchor_year = _detect_consulting_pm_anchor_year(conn, start_year)
    total = 0
    for y in range(start_year, start_year + years_ahead + 1):
        total += int(_seed_consulting_preloaded_activities(conn, y, anchor_year=anchor_year) or 0)
    return total

def _apply_versioned_migrations(conn):
    _ensure_schema_migrations(conn)

    # M1: user lockout + password reset
    mid = "2026-03-10_01_user_lockout_password_reset"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "users", "failed_attempts", "failed_attempts INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "users", "locked_until", "locked_until INTEGER")
            ensure_column(conn, "users", "last_login_at", "last_login_at TEXT")
            ensure_column(conn, "users", "password_updated_at", "password_updated_at TEXT")
        except Exception:
            pass
        _safe_executescript(conn, '''
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at INTEGER NOT NULL,
            used_at TEXT,
            request_ip TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id);
        ''')
        _mark_migration(conn, mid, "Lockout + password reset")

    # M2: document workflow ISO 9001 (status + approvals + obsolescence)
    mid = "2026-03-10_02_documents_workflow"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "documents", "status", "status TEXT NOT NULL DEFAULT 'approved'")
            ensure_column(conn, "documents", "change_reason", "change_reason TEXT")
            ensure_column(conn, "documents", "review_comment", "review_comment TEXT")
            ensure_column(conn, "documents", "approved_by", "approved_by INTEGER")
            ensure_column(conn, "documents", "approved_at", "approved_at TEXT")
            ensure_column(conn, "documents", "effective_at", "effective_at TEXT")
            ensure_column(conn, "documents", "obsolete_at", "obsolete_at TEXT")
        except Exception:
            pass
        try:
            ensure_column(conn, "document_versions", "status", "status TEXT NOT NULL DEFAULT 'approved'")
            ensure_column(conn, "document_versions", "change_reason", "change_reason TEXT")
            ensure_column(conn, "document_versions", "review_comment", "review_comment TEXT")
            ensure_column(conn, "document_versions", "reviewed_by", "reviewed_by INTEGER")
            ensure_column(conn, "document_versions", "reviewed_at", "reviewed_at TEXT")
            ensure_column(conn, "document_versions", "approved_by", "approved_by INTEGER")
            ensure_column(conn, "document_versions", "approved_at", "approved_at TEXT")
            ensure_column(conn, "document_versions", "rejected_by", "rejected_by INTEGER")
            ensure_column(conn, "document_versions", "rejected_at", "rejected_at TEXT")
            ensure_column(conn, "document_versions", "effective_at", "effective_at TEXT")
            ensure_column(conn, "document_versions", "obsolete_at", "obsolete_at TEXT")
        except Exception:
            pass
        _safe_executescript(conn, '''
        CREATE INDEX IF NOT EXISTS idx_doc_versions_group_status ON document_versions(doc_group_key, status, version_no);
        CREATE INDEX IF NOT EXISTS idx_documents_group_current ON documents(group_key, is_current, status);
        ''')
        _mark_migration(conn, mid, "Docs workflow + indexes")

    # M4: Petroleum owners + renewal control
    mid = "2026-03-24_04_petroleum_owner_registry"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "stations", "petroleum_owner_id", "petroleum_owner_id INTEGER")
        except Exception:
            pass
        _safe_executescript(conn, '''
        CREATE TABLE IF NOT EXISTS petroleum_owner_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            short_code TEXT NOT NULL UNIQUE,
            color_hex TEXT NOT NULL DEFAULT '#D4AF37',
            phone TEXT,
            email TEXT,
            notes TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS petroleum_doc_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            accent_color TEXT NOT NULL DEFAULT '#D4AF37',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS petroleum_station_control (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id INTEGER NOT NULL,
            doc_type_id INTEGER NOT NULL,
            start_date TEXT,
            renewal_date TEXT,
            document_status TEXT NOT NULL DEFAULT 'vigente' CHECK(document_status IN ('vigente','debe_documento','en_revision','vencido','no_aplica')),
            payment_status TEXT NOT NULL DEFAULT 'pendiente' CHECK(payment_status IN ('pagado','pendiente','vencido','no_aplica')),
            last_payment_date TEXT,
            amount_due REAL,
            notes TEXT,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            UNIQUE(station_id, doc_type_id),
            FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
            FOREIGN KEY(doc_type_id) REFERENCES petroleum_doc_types(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_petroleum_station_control_station ON petroleum_station_control(station_id, renewal_date, document_status, payment_status);
        CREATE INDEX IF NOT EXISTS idx_stations_petroleum_owner ON stations(brand, petroleum_owner_id);
        INSERT OR IGNORE INTO petroleum_doc_types (code, title, accent_color, sort_order, is_active) VALUES
            ('nom005', 'NOM-005', '#22C55E', 10, 1),
            ('nom016', 'NOM-016', '#EF4444', 20, 1),
            ('anexo3031', 'Anexo 30-31', '#111827', 30, 1);
        ''')
        _mark_migration(conn, mid, "Petroleum owners and renewal control")


    # M3: CAPA / No conformidades (ISO 9001)
    mid = "2026-03-10_03_capa"
    if not _migration_applied(conn, mid):
        _safe_executescript(conn, '''
        CREATE TABLE IF NOT EXISTS nonconformities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL DEFAULT 'consulting',
            station_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            severity TEXT NOT NULL DEFAULT 'media',
            status TEXT NOT NULL DEFAULT 'abierta',
            detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            detected_by INTEGER,
            root_cause TEXT,
            corrective_action TEXT,
            preventive_action TEXT,
            owner_user_id INTEGER,
            due_date TEXT,
            closed_at TEXT,
            effectiveness_check TEXT,
            FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
            FOREIGN KEY(detected_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS capa_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nc_id INTEGER NOT NULL,
            action_type TEXT NOT NULL CHECK(action_type IN ('correctiva','preventiva','contencion')),
            description TEXT NOT NULL,
            owner_user_id INTEGER,
            due_date TEXT,
            status TEXT NOT NULL DEFAULT 'pendiente',
            done_at TEXT,
            evidence_path TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(nc_id) REFERENCES nonconformities(id) ON DELETE CASCADE,
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_nc_brand_station ON nonconformities(brand, station_id, status);
        CREATE INDEX IF NOT EXISTS idx_capa_nc ON capa_actions(nc_id, status);
        ''')
        _mark_migration(conn, mid, "CAPA tables")


    # M5: DOCX template engine — admite también PDF como archivo de plantilla
    mid = "2026-05-12_01_docx_templates_pdf_support"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "docx_templates", "file_type",
                          "file_type TEXT NOT NULL DEFAULT 'docx'")
        except Exception:
            pass
        _mark_migration(conn, mid, "docx_templates.file_type (docx|pdf)")

    # M6: Consolidación — el motor docx_templates se fusiona en doc_templates.
    # Se agregan columnas para soportar DOCX, código corto, descripción, borradores
    # (is_active) y un timestamp de actualización; además una tabla de versiones.
    mid = "2026-05-12_02_doc_templates_unify_with_docx"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "doc_templates", "code", "code TEXT")
            ensure_column(conn, "doc_templates", "description", "description TEXT")
            ensure_column(conn, "doc_templates", "file_type",
                          "file_type TEXT NOT NULL DEFAULT 'pdf'")
            ensure_column(conn, "doc_templates", "is_active",
                          "is_active INTEGER NOT NULL DEFAULT 1")
            ensure_column(conn, "doc_templates", "updated_at", "updated_at TEXT")
        except Exception:
            pass
        _safe_executescript(conn, '''
        CREATE TABLE IF NOT EXISTS doc_template_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            version_label TEXT NOT NULL,
            file_path TEXT NOT NULL,
            original_filename TEXT,
            file_size_bytes INTEGER,
            notes TEXT,
            is_current INTEGER NOT NULL DEFAULT 0,
            uploaded_by INTEGER,
            uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES doc_templates(id) ON DELETE CASCADE,
            FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(template_id, version_label)
        );
        CREATE INDEX IF NOT EXISTS idx_doc_template_versions_current
            ON doc_template_versions(template_id, is_current, uploaded_at);
        ''')

        # Para plantillas que ya existían (sin versiones), creamos una v1.0
        # apuntando al file_path actual para mantener historial homogéneo.
        try:
            for row in conn.execute(
                "SELECT id, file_path, created_by, created_at FROM doc_templates "
                "WHERE file_path IS NOT NULL "
                "AND id NOT IN (SELECT DISTINCT template_id FROM doc_template_versions)"
            ).fetchall():
                conn.execute(
                    "INSERT INTO doc_template_versions "
                    "(template_id, version_label, file_path, is_current, uploaded_by, uploaded_at) "
                    "VALUES (?,?,?,1,?,COALESCE(?, CURRENT_TIMESTAMP))",
                    (int(row["id"]), "v1.0", row["file_path"],
                     row["created_by"], row["created_at"]),
                )
            conn.commit()
        except Exception:
            pass

        _mark_migration(conn, mid, "Unify docx_templates into doc_templates")

    # M7: Migrar datos del motor docx_templates obsoleto → doc_templates.
    # Solo copia filas cuyo (brand, module, code) todavía no exista en doc_templates.
    # Es una migración nice-to-have: no falla si docx_templates ya no existe.
    mid = "2026-05-12_03_migrate_docx_data_to_doc_templates"
    if not _migration_applied(conn, mid):
        try:
            rows = conn.execute(
                "SELECT id, brand, module, code, name, description, file_type, "
                "is_published, is_active, created_by, created_at "
                "FROM docx_templates"
            ).fetchall()
            for row in rows:
                code = row["code"] if isinstance(row, dict) else row[2]
                brand = row["brand"] if isinstance(row, dict) else row[1]
                module = row["module"] if isinstance(row, dict) else row[2]
                already = conn.execute(
                    "SELECT 1 FROM doc_templates WHERE brand=? AND module=? AND code=?",
                    (row["brand"], row["module"], row["code"]),
                ).fetchone()
                if already:
                    continue
                conn.execute(
                    "INSERT INTO doc_templates "
                    "(brand, module, name, code, description, file_path, month_key, "
                    "file_type, field_schema_json, is_published, is_active, "
                    "created_by, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row["brand"], row["module"], row["name"],
                        row["code"], row["description"],
                        None,   # file_path — se tomará de la versión
                        None,   # month_key
                        row["file_type"] or "docx",
                        "[]",
                        row["is_published"] or 0,
                        row["is_active"] if row["is_active"] is not None else 1,
                        row["created_by"], row["created_at"],
                    ),
                )
                new_id = conn.execute(
                    "SELECT last_insert_rowid() AS id"
                ).fetchone()["id"]
                # Copiar versiones
                versions = conn.execute(
                    "SELECT version_label, file_path, original_filename, "
                    "file_size_bytes, notes, is_current, uploaded_by, uploaded_at "
                    "FROM docx_template_versions WHERE template_id=?",
                    (int(row["id"]),),
                ).fetchall()
                for v in versions:
                    conn.execute(
                        "INSERT INTO doc_template_versions "
                        "(template_id, version_label, file_path, original_filename, "
                        "file_size_bytes, notes, is_current, uploaded_by, uploaded_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            int(new_id),
                            v["version_label"], v["file_path"],
                            v["original_filename"], v["file_size_bytes"],
                            v["notes"], v["is_current"],
                            v["uploaded_by"], v["uploaded_at"],
                        ),
                    )
                # Actualizar file_path principal con el de la versión current
                cur_ver = conn.execute(
                    "SELECT file_path FROM doc_template_versions "
                    "WHERE template_id=? AND is_current=1 LIMIT 1",
                    (int(new_id),),
                ).fetchone()
                if cur_ver:
                    conn.execute(
                        "UPDATE doc_templates SET file_path=? WHERE id=?",
                        (cur_ver["file_path"], int(new_id)),
                    )
            conn.commit()
        except Exception:
            pass  # docx_templates puede no existir en instalaciones nuevas
        _mark_migration(conn, mid, "Migrate docx_templates data to doc_templates")

    # M8: Eliminar tablas del motor docx_templates (ya obsoleto).
    # Se ejecuta después de M7 para garantizar que los datos fueron copiados.
    mid = "2026-05-12_04_drop_docx_tables"
    if not _migration_applied(conn, mid):
        _safe_executescript(conn, """
        DROP TABLE IF EXISTS docx_template_fields;
        DROP TABLE IF EXISTS docx_template_versions;
        DROP TABLE IF EXISTS docx_generated_documents;
        DROP TABLE IF EXISTS docx_templates;
        """)
        _mark_migration(conn, mid, "Drop obsolete docx_* tables")

    # M9: Logo por plantilla — permite al admin subir un logo que se
    # incrusta en la celda de encabezado del DOCX/PDF.
    mid = "2026-05-13_01_doc_templates_logo_path"
    if not _migration_applied(conn, mid):
        try:
            ensure_column(conn, "doc_templates", "logo_path", "logo_path TEXT")
        except Exception:
            pass
        _mark_migration(conn, mid, "doc_templates.logo_path for header logo")

    # M10: Nuevo modelo de estados para incidencias (pendiente/leido/atendido/reportado)
    # + columnas acknowledged_by / acknowledged_at para registrar cuándo el jefe la marca leída.
    # SQLite no permite ALTER al CHECK constraint, así que el patrón es:
    # tabla nueva → copiar con mapeo de status → drop → rename → reindexar.
    mid = "2026-05-29_01_incidents_v2_status_model"
    if not _migration_applied(conn, mid):
        try:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='incident_logs'"
            ).fetchone()
            if has_table:
                _safe_executescript(conn, """
                CREATE TABLE incident_logs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL DEFAULT 'consulting',
                    station_id INTEGER,
                    module TEXT,
                    category TEXT,
                    severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low','medium','high','critical')),
                    status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','leido','atendido','reportado')),
                    title TEXT NOT NULL,
                    description TEXT,
                    folio TEXT,
                    created_by INTEGER,
                    assigned_to INTEGER,
                    acknowledged_by INTEGER,
                    acknowledged_at TEXT,
                    resolved_by INTEGER,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT,
                    FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(acknowledged_by) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL
                );

                INSERT INTO incident_logs_new (
                    id, brand, station_id, module, category, severity, status,
                    title, description, folio, created_by, assigned_to,
                    acknowledged_by, acknowledged_at,
                    resolved_by, resolved_at, created_at, updated_at
                )
                SELECT
                    id, brand, station_id, module, category, severity,
                    CASE status
                        WHEN 'open' THEN 'pendiente'
                        WHEN 'in_progress' THEN 'leido'
                        WHEN 'closed' THEN 'atendido'
                        ELSE 'pendiente'
                    END AS status,
                    title, description, folio, created_by, assigned_to,
                    CASE WHEN status = 'closed' THEN resolved_by ELSE NULL END AS acknowledged_by,
                    CASE WHEN status = 'closed' THEN resolved_at ELSE NULL END AS acknowledged_at,
                    resolved_by, resolved_at, created_at, updated_at
                FROM incident_logs;

                DROP TABLE incident_logs;
                ALTER TABLE incident_logs_new RENAME TO incident_logs;
                CREATE INDEX IF NOT EXISTS idx_incident_scope
                    ON incident_logs(brand, station_id, status, severity, created_at);
                """)
        except Exception:
            pass
        _mark_migration(conn, mid, "Incidents v2: status model + acknowledged_by/at")


def init_db():
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS stations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        name TEXT NOT NULL,
        code TEXT UNIQUE NOT NULL,
        station_number TEXT,
        group_name TEXT,
        state TEXT,
        city TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        monthly_status TEXT NOT NULL DEFAULT 'active' CHECK(monthly_status IN ('active','view_only','expired')),
        monthly_end TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','operador','jefe_estacion','contador','auditor')),
        primary_brand TEXT NOT NULL DEFAULT 'consulting',
        allowed_brands TEXT NOT NULL DEFAULT 'consulting,petroleum',
        station_id INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        title TEXT NOT NULL,
        description TEXT,
        evidence_required INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    /* Calendar assignments (FullCalendar) */
    CREATE TABLE IF NOT EXISTS calendar_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        activity_id INTEGER,
        title TEXT NOT NULL,
        start_date TEXT NOT NULL, /* YYYY-MM-DD */
        end_date TEXT,           /* optional */
        repeat_kind TEXT NOT NULL DEFAULT 'once',
        station_id INTEGER,      /* NULL => all stations */
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE SET NULL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        event_id INTEGER,
        activity_id INTEGER,
        station_id INTEGER NOT NULL,
        user_id INTEGER,
        notes TEXT,
        evidence_path TEXT,
        status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted','reviewed','approved','rejected')),
        score INTEGER,
        review_notes TEXT,
        reviewed_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        FOREIGN KEY(event_id) REFERENCES calendar_events(id) ON DELETE SET NULL,
        FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE SET NULL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
    );

    /* Independent Agenda tables (Petroleum only; keeps Agenda separate from Consulting Activities) */
    CREATE TABLE IF NOT EXISTS agenda_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'petroleum',
        title TEXT NOT NULL,
        description TEXT,
        evidence_required INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        manual_path TEXT,
        manual_name TEXT,
        extra_path TEXT,
        extra_name TEXT,
        recurrence TEXT,
        target_station_id INTEGER,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(target_station_id) REFERENCES stations(id) ON DELETE SET NULL
    );

    /* Calendar assignments for Agenda (FullCalendar) */
    CREATE TABLE IF NOT EXISTS agenda_calendar_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'petroleum',
        activity_id INTEGER,
        title TEXT NOT NULL,
        start_date TEXT NOT NULL, /* YYYY-MM-DD */
        end_date TEXT,           /* optional */
        repeat_kind TEXT NOT NULL DEFAULT 'once',
        station_id INTEGER,      /* NULL => all stations */
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(activity_id) REFERENCES agenda_activities(id) ON DELETE SET NULL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS agenda_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'petroleum',
        event_id INTEGER,
        activity_id INTEGER,
        station_id INTEGER NOT NULL,
        user_id INTEGER,
        notes TEXT,
        evidence_path TEXT,
        status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted','reviewed','approved','rejected')),
        score INTEGER,
        review_notes TEXT,
        reviewed_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        signature_name TEXT,
        signature_ip TEXT,
        signature_at TEXT,
        FOREIGN KEY(event_id) REFERENCES agenda_calendar_events(id) ON DELETE SET NULL,
        FOREIGN KEY(activity_id) REFERENCES agenda_activities(id) ON DELETE SET NULL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
    );


    CREATE TABLE IF NOT EXISTS pipas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        plates TEXT,
        operator_name TEXT,
        arrival_time TEXT,
        departure_time TEXT,
        fuel_type TEXT NOT NULL CHECK(fuel_type IN ('magna','premium','diesel')),
        liters REAL NOT NULL,
        ticket_path TEXT,
        factura_path TEXT,
        before_path TEXT,
        after_path TEXT,
        signature_name TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        period_start TEXT,
        period_end TEXT,
        proof_path TEXT,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','validated','rejected')),
        reviewed_by INTEGER,
        reviewed_at TEXT,
        invoice_path TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('green','yellow','red')),
        title TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_by INTEGER,
        closed_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(closed_by) REFERENCES users(id) ON DELETE SET NULL
    );

    /* Optional templates for quickly creating station alerts */
    CREATE TABLE IF NOT EXISTS alert_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        severity TEXT NOT NULL CHECK(severity IN ('green','yellow','red')),
        title TEXT NOT NULL,
        description TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS pumps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        pump_code TEXT NOT NULL,
        location TEXT,
        status TEXT NOT NULL DEFAULT 'green' CHECK(status IN ('green','yellow','red')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(station_id, pump_code),
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS maintenance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        pump_id INTEGER,
        kind TEXT NOT NULL CHECK(kind IN ('preventivo','correctivo','calibracion')),
        technician TEXT,
        notes TEXT,
        evidence_before TEXT,
        evidence_after TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(pump_id) REFERENCES pumps(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS bitacoras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('daily','weekly','monthly')),
        ref_date TEXT NOT NULL, /* YYYY-MM-DD (day), or first day of week/month */
        notes TEXT,
        evidence_path TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS station_profiles (        brand TEXT NOT NULL DEFAULT 'consulting',

        station_id INTEGER PRIMARY KEY,
        permit_number TEXT,
        legal_name TEXT,
        fiel_cer_path TEXT,
        fiel_key_path TEXT,
        fiel_updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        entity TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        station_id INTEGER,
        author_user_id INTEGER,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(author_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        user_id INTEGER,
        station_id INTEGER,
        type TEXT,
        title TEXT NOT NULL,
        body TEXT,
        url TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL
    );

    /* Prevent duplicate scheduled notifications (due/overdue) */
    CREATE TABLE IF NOT EXISTS notification_keys (        brand TEXT NOT NULL DEFAULT 'consulting',

        key TEXT PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    /* Minimal key/value for scheduled jobs */
    CREATE TABLE IF NOT EXISTS system_state (        brand TEXT NOT NULL DEFAULT 'consulting',

        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        module TEXT NOT NULL,
        section TEXT NOT NULL,
        title TEXT,
        file_path TEXT NOT NULL,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );


    
/* Document versioning (keeps history, allows restore) */
CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_group_key TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    title TEXT,
    module TEXT,
    section TEXT,
    station_id INTEGER,
    brand TEXT NOT NULL DEFAULT 'consulting',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_group_key, version_no),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
);

/* Delegation: allow chiefs/auditors to access multiple stations */
CREATE TABLE IF NOT EXISTS user_station_access (
    user_id INTEGER NOT NULL,
    station_id INTEGER NOT NULL,
    brand TEXT NOT NULL DEFAULT 'consulting',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, station_id, brand),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
);

/* Petroleum: interactive compliance screen */
CREATE TABLE IF NOT EXISTS compliance_items (        brand TEXT NOT NULL DEFAULT 'consulting',

    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    section TEXT NOT NULL DEFAULT 'Cumplimiento',
    sort_order INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS compliance_records (
    brand TEXT NOT NULL DEFAULT 'petroleum',
    station_id INTEGER NOT NULL,
    item_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_review','approved','rejected')),
    status_note TEXT,
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(brand, station_id, item_code),
    FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
    FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(item_code) REFERENCES compliance_items(code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS compliance_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL DEFAULT 'petroleum',
    station_id INTEGER NOT NULL,
    item_code TEXT NOT NULL,
    version INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    original_name TEXT,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(brand, station_id, item_code, version),
    FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
    FOREIGN KEY(item_code) REFERENCES compliance_items(code) ON DELETE CASCADE
);

/* Petroleum norm/annex documents by fuel type (global, versioned) */
CREATE TABLE IF NOT EXISTS petroleum_norm_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL DEFAULT 'petroleum',
    fuel_type TEXT NOT NULL,                -- magna|premium|diesel|other
    doc_key TEXT NOT NULL,                  -- nom_005|nom_016|anexo_30_31|...
    title TEXT NOT NULL,
    version INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    original_name TEXT,
    uploaded_by INTEGER,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(brand, fuel_type, doc_key, version),
    FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        actor_user_id INTEGER,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id TEXT,
        meta_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

CREATE TABLE IF NOT EXISTS internal_signatures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        signer_user_id INTEGER,
        signer_name TEXT,
        signer_role TEXT,
        signer_ip TEXT,
        details_json TEXT,
        signed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(signer_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

CREATE TABLE IF NOT EXISTS evidence_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        caption TEXT,
        uploaded_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    # ---- lightweight migrations for multi-empresa (brand) support ----
    # Some installs may have older DBs without these columns.
    for tbl in [
        "stations","users","activities","calendar_events","submissions","pipas","payments",
        "alerts","alert_templates","pumps","maintenance","bitacoras","station_profiles",
        "comments","notifications","notification_keys","system_state","documents","compliance_items","audit_log"
    ]:
        try:
            ensure_column(conn, tbl, "brand", "brand TEXT NOT NULL DEFAULT 'consulting'")
        except Exception:
            pass

    try:
        ensure_column(conn, "stations", "station_number", "station_number TEXT")
        ensure_column(conn, "stations", "group_name", "group_name TEXT")
    except Exception:
        pass
    try:
        ensure_column(conn, "users", "primary_brand", "primary_brand TEXT NOT NULL DEFAULT 'consulting'")
        ensure_column(conn, "users", "email", "email TEXT")
        ensure_column(conn, "users", "allowed_brands", "allowed_brands TEXT NOT NULL DEFAULT 'consulting,petroleum'")
    except Exception:
        pass

    # Petroleum compliance: expiry fields (traffic light)
    try:
        ensure_column(conn, "compliance_records", "issue_date", "issue_date TEXT")
        ensure_column(conn, "compliance_records", "expiry_date", "expiry_date TEXT")
    except Exception:
        pass


    # Helpful indexes
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_brand_read ON notifications(brand, is_read, created_at)")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stations_brand ON stations(brand)")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activities_brand ON activities(brand)")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_events_brand_start ON calendar_events(brand, start)")
    except Exception:
        pass
    # Lightweight migrations (add missing columns on existing DBs)
    ensure_column(conn, "calendar_events", "repeat_kind", "repeat_kind TEXT NOT NULL DEFAULT 'once'")

    # Multi-company support (Consulting / Petroleum)
    ensure_column(conn, "stations", "brand", "brand TEXT NOT NULL DEFAULT 'consulting'")
    ensure_column(conn, "users", "allowed_brands", "allowed_brands TEXT NOT NULL DEFAULT 'consulting'")
    ensure_column(conn, "users", "primary_brand", "primary_brand TEXT NOT NULL DEFAULT 'consulting'")
    ensure_column(conn, "users", "email", "email TEXT")
    for t in ["activities","calendar_events","submissions","pipas","payments","alerts","alert_templates","pumps","maintenance","bitacoras","station_profiles","comments","notifications","documents","audit_log"]:
        ensure_column(conn, t, "brand", "brand TEXT NOT NULL DEFAULT 'consulting'")

    # Notifications type (optional)
    ensure_column(conn, "notifications", "type", "type TEXT")

    # Documents can be global (station_id NULL) or station-scoped
    ensure_column(conn, "documents", "station_id", "station_id INTEGER")
    ensure_column(conn, "documents", "group_key", "group_key TEXT")
    ensure_column(conn, "documents", "version_no", "version_no INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "documents", "is_current", "is_current INTEGER NOT NULL DEFAULT 1")

    # Optional expiry (for reminders / traffic light in document libraries)
    try:
        ensure_column(conn, "document_versions", "expires_at", "expires_at TEXT")
    except Exception:
        pass

    # Stations extra fields
    ensure_column(conn, "stations", "group_name", "group_name TEXT")
    ensure_column(conn, "stations", "station_number", "station_number INTEGER")

    # Station private data (used to autofill templates: SASISOPA, SGM, normativas, anexos)
    # Only admins can edit these via the profile API. Logos are stored as upload paths.
    for col, ddl in (
        ("logo_empresa_path",      "logo_empresa_path TEXT"),
        ("logo_estacion_path",     "logo_estacion_path TEXT"),
        ("rfc",                    "rfc TEXT"),
        ("domicilio",              "domicilio TEXT"),
        ("permiso_cre",            "permiso_cre TEXT"),
        ("representante_legal",    "representante_legal TEXT"),
        ("responsable_operativo",  "responsable_operativo TEXT"),
        ("responsable_sasisopa",   "responsable_sasisopa TEXT"),
        ("responsable_sgm",        "responsable_sgm TEXT"),
        ("correo",                 "correo TEXT"),
        ("telefono",               "telefono TEXT"),
        ("updated_at",             "updated_at TEXT"),
    ):
        try:
            ensure_column(conn, "station_profiles", col, ddl)
        except Exception:
            pass

    # SASISOPA documental (Consulting)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS doc_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        name TEXT NOT NULL,
        code TEXT,
        description TEXT,
        file_path TEXT NOT NULL,
        month_key TEXT,
        file_type TEXT NOT NULL DEFAULT 'pdf',
        field_schema_json TEXT NOT NULL DEFAULT '[]',
        is_published INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS doc_template_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        version_label TEXT NOT NULL,
        file_path TEXT NOT NULL,
        original_filename TEXT,
        file_size_bytes INTEGER,
        notes TEXT,
        is_current INTEGER NOT NULL DEFAULT 0,
        uploaded_by INTEGER,
        uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES doc_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(template_id, version_label)
    );

    CREATE TABLE IF NOT EXISTS doc_requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        template_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        open_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        station_id INTEGER,
        assigned_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES doc_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(assigned_user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS doc_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        requirement_id INTEGER NOT NULL,
        operator_id INTEGER NOT NULL,
        attempt_no INTEGER NOT NULL DEFAULT 1,
        submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        pdf_path TEXT NOT NULL,
        field_values_json TEXT NOT NULL DEFAULT '{}',
        review_status TEXT NOT NULL DEFAULT 'PENDING',
        review_comment TEXT,
        reviewed_by INTEGER,
        reviewed_at TEXT,
        next_auto_reopen_at TEXT,
        FOREIGN KEY(requirement_id) REFERENCES doc_requirements(id) ON DELETE CASCADE,
        FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(requirement_id, operator_id, attempt_no)
    );

    CREATE TABLE IF NOT EXISTS doc_unlocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        requirement_id INTEGER NOT NULL,
        operator_id INTEGER NOT NULL,
        unlocked_by INTEGER NOT NULL,
        unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reason TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(requirement_id) REFERENCES doc_requirements(id) ON DELETE CASCADE,
        FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(unlocked_by) REFERENCES users(id) ON DELETE CASCADE
    );


    CREATE TABLE IF NOT EXISTS doc_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        module TEXT NOT NULL DEFAULT 'sasisopa',
        station_id INTEGER,
        template_id INTEGER NOT NULL,
        title TEXT,
        pdf_path TEXT NOT NULL,
        field_values_json TEXT NOT NULL DEFAULT '{}',
        updated_by INTEGER,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES doc_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(brand, module, station_id)
    );

    CREATE INDEX IF NOT EXISTS idx_doc_records_brand_module_station ON doc_records(brand, module, station_id, updated_at);

    /* Calibraciones (Consulting) - Tanques por estación (admin-only por ahora) */
    CREATE TABLE IF NOT EXISTS cal_tanks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        pdf_path TEXT,
        pdf_uploaded_at TEXT,
        pdf_uploaded_by INTEGER,
        sonda_pdf_path TEXT,
        sonda_pdf_uploaded_at TEXT,
        sonda_pdf_uploaded_by INTEGER,
        temp_pdf_path TEXT,
        temp_pdf_uploaded_at TEXT,
        temp_pdf_uploaded_by INTEGER,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(pdf_uploaded_by) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_cal_tanks_brand_station ON cal_tanks(brand, station_id);
    """)

    ensure_column(conn, "doc_templates", "module", "module TEXT NOT NULL DEFAULT 'sasisopa'")
    ensure_column(conn, "doc_requirements", "module", "module TEXT NOT NULL DEFAULT 'sasisopa'")
    ensure_column(conn, "doc_submissions", "module", "module TEXT NOT NULL DEFAULT 'sasisopa'")
    ensure_column(conn, "doc_unlocks", "module", "module TEXT NOT NULL DEFAULT 'sasisopa'")

    # Calibraciones: extender cal_tanks para soportar documentos por tanque (sonda/temperatura)
    ensure_column(conn, "cal_tanks", "sonda_pdf_path", "sonda_pdf_path TEXT")
    ensure_column(conn, "cal_tanks", "sonda_pdf_uploaded_at", "sonda_pdf_uploaded_at TEXT")
    ensure_column(conn, "cal_tanks", "sonda_pdf_uploaded_by", "sonda_pdf_uploaded_by INTEGER")
    ensure_column(conn, "cal_tanks", "temp_pdf_path", "temp_pdf_path TEXT")
    ensure_column(conn, "cal_tanks", "temp_pdf_uploaded_at", "temp_pdf_uploaded_at TEXT")
    ensure_column(conn, "cal_tanks", "temp_pdf_uploaded_by", "temp_pdf_uploaded_by INTEGER")
    try:
        conn.execute("UPDATE doc_templates SET module='sasisopa' WHERE module IS NULL OR TRIM(module)=''")
        conn.execute("UPDATE doc_requirements SET module='sasisopa' WHERE module IS NULL OR TRIM(module)=''")
        conn.execute("UPDATE doc_submissions SET module='sasisopa' WHERE module IS NULL OR TRIM(module)=''")
        conn.execute("UPDATE doc_unlocks SET module='sasisopa' WHERE module IS NULL OR TRIM(module)=''")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_templates_brand ON doc_templates(brand, module, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_requirements_scope ON doc_requirements(brand, module, open_date, due_date, station_id, assigned_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_submissions_scope ON doc_submissions(brand, module, requirement_id, operator_id, review_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_unlocks_scope ON doc_unlocks(brand, module, requirement_id, operator_id, is_active)")
    except Exception:
        pass


    # Advanced features: branding, incidents, correction tasks, drawn signatures, help center
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS branding_settings (
        brand TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (brand, key)
    );

    CREATE TABLE IF NOT EXISTS incident_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        module TEXT,
        category TEXT,
        severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low','medium','high','critical')),
        status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','leido','atendido','reportado')),
        title TEXT NOT NULL,
        description TEXT,
        folio TEXT,
        created_by INTEGER,
        assigned_to INTEGER,
        acknowledged_by INTEGER,
        acknowledged_at TEXT,
        resolved_by INTEGER,
        resolved_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(acknowledged_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS correction_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        module TEXT,
        title TEXT NOT NULL,
        description TEXT,
        related_entity TEXT,
        related_entity_id TEXT,
        source_status TEXT,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','done','cancelled')),
        priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high','urgent')),
        folio TEXT,
        created_by INTEGER,
        assigned_to INTEGER,
        completed_by INTEGER,
        completed_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(completed_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS drawn_signatures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        signer_user_id INTEGER,
        file_path TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(signer_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS help_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        category TEXT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        is_featured INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tramites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        station_id INTEGER,
        client_name TEXT,
        tramite_type TEXT NOT NULL,
        dependency TEXT,
        subject TEXT NOT NULL,
        start_date TEXT,
        due_date TEXT,
        responsible_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','en_proceso','en_revision','requiere_correccion','finalizado','vencido','cancelado')),
        observations TEXT,
        priority TEXT NOT NULL DEFAULT 'media' CHECK(priority IN ('baja','media','alta','critica')),
        attachment_path TEXT,
        folio TEXT,
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS normative_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'petroleum',
        code TEXT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        periodicity TEXT NOT NULL DEFAULT 'mensual',
        default_risk TEXT NOT NULL DEFAULT 'medio',
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS normativas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'petroleum',
        station_id INTEGER NOT NULL,
        catalog_id INTEGER,
        norma_title TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        periodicity TEXT NOT NULL DEFAULT 'mensual',
        compliance_date TEXT,
        next_due_date TEXT,
        responsible_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'en_proceso' CHECK(status IN ('cumple','proximo_a_vencer','vencido','en_proceso','no_aplica','en_revision')),
        observations TEXT,
        risk_level TEXT NOT NULL DEFAULT 'medio' CHECK(risk_level IN ('bajo','medio','alto','critico')),
        evidence_path TEXT,
        folio TEXT,
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(catalog_id) REFERENCES normative_catalog(id) ON DELETE SET NULL,
        FOREIGN KEY(responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
    );
    

    CREATE TABLE IF NOT EXISTS expediente_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        area TEXT NOT NULL CHECK(area IN ('tramites','normativas')),
        code TEXT,
        title TEXT NOT NULL,
        description TEXT,
        is_required INTEGER NOT NULL DEFAULT 1,
        default_validity_days INTEGER,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS expediente_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        area TEXT NOT NULL CHECK(area IN ('tramites','normativas')),
        station_id INTEGER,
        owner_name TEXT,
        template_id INTEGER,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'faltante' CHECK(status IN ('faltante','vigente','proximo_a_vencer','vencido','en_revision','no_aplica')),
        issue_date TEXT,
        expiry_date TEXT,
        notes TEXT,
        current_file_path TEXT,
        version_count INTEGER NOT NULL DEFAULT 0,
        folio TEXT,
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(template_id) REFERENCES expediente_templates(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS expediente_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        version_no INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        notes TEXT,
        uploaded_by INTEGER,
        uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(record_id) REFERENCES expediente_records(id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS document_deadlines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        source_table TEXT NOT NULL,
        source_id INTEGER NOT NULL,
        module TEXT NOT NULL,
        station_id INTEGER,
        owner_name TEXT,
        client_name TEXT,
        title TEXT NOT NULL,
        folio TEXT,
        issue_date TEXT,
        due_date TEXT NOT NULL,
        renewable INTEGER NOT NULL DEFAULT 1,
        periodicity TEXT,
        responsible_user_id INTEGER,
        status TEXT,
        notes TEXT,
        file_path TEXT,
        version_count INTEGER NOT NULL DEFAULT 0,
        reminder_days TEXT NOT NULL DEFAULT '60,30,15,7,3,1,0',
        scope_label TEXT,
        meta_json TEXT,
        last_notice_at TEXT,
        last_notice_kind TEXT,
        last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(brand, source_table, source_id)
    );

    CREATE TABLE IF NOT EXISTS deadline_notifications_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deadline_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        notice_key TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT 'in_app',
        sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(deadline_id) REFERENCES document_deadlines(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(deadline_id, user_id, notice_key, channel)
    );

    CREATE TABLE IF NOT EXISTS document_renewal_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        deadline_id INTEGER,
        source_table TEXT NOT NULL,
        source_id INTEGER NOT NULL,
        old_due_date TEXT,
        new_due_date TEXT,
        old_status TEXT,
        new_status TEXT,
        old_file_path TEXT,
        new_file_path TEXT,
        notes TEXT,
        renewed_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(deadline_id) REFERENCES document_deadlines(id) ON DELETE SET NULL,
        FOREIGN KEY(renewed_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS backup_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        file_path TEXT NOT NULL,
        file_size_bytes INTEGER,
        kind TEXT NOT NULL DEFAULT 'manual' CHECK(kind IN ('manual','auto','scheduled','pre_change')),
        triggered_by INTEGER,
        notes TEXT,
        success INTEGER NOT NULL DEFAULT 1,
        error_message TEXT,
        FOREIGN KEY(triggered_by) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_backup_logs_created ON backup_logs(created_at DESC);

    /* DOCX template engine (admin uploads .docx with <<VARIABLE>> placeholders).
       Coexists with the legacy PDF+coordinates engine in doc_templates. */
    CREATE TABLE IF NOT EXISTS docx_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        module TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        file_type TEXT NOT NULL DEFAULT 'docx',
        current_version_id INTEGER,
        is_published INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        UNIQUE(brand, module, code),
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS docx_template_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        version_label TEXT NOT NULL,
        file_path TEXT NOT NULL,
        original_filename TEXT,
        file_size_bytes INTEGER,
        notes TEXT,
        is_current INTEGER NOT NULL DEFAULT 0,
        uploaded_by INTEGER,
        uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES docx_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(template_id, version_label)
    );

    CREATE TABLE IF NOT EXISTS docx_template_fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        version_id INTEGER NOT NULL,
        variable_name TEXT NOT NULL,
        label TEXT,
        field_kind TEXT NOT NULL DEFAULT 'manual'
            CHECK(field_kind IN ('auto','manual','fixed','image','signature','date_today')),
        auto_source TEXT,
        fixed_value TEXT,
        placeholder TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_required INTEGER NOT NULL DEFAULT 0,
        field_type TEXT NOT NULL DEFAULT 'text'
            CHECK(field_type IN ('text','textarea','date','number')),
        FOREIGN KEY(template_id) REFERENCES docx_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(version_id) REFERENCES docx_template_versions(id) ON DELETE CASCADE,
        UNIQUE(version_id, variable_name)
    );

    CREATE TABLE IF NOT EXISTS docx_generated_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL DEFAULT 'consulting',
        template_id INTEGER NOT NULL,
        version_id INTEGER NOT NULL,
        station_id INTEGER,
        title TEXT,
        docx_path TEXT,
        pdf_path TEXT,
        field_values_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'borrador'
            CHECK(status IN ('borrador','en_revision','aprobado','cancelado','enviado_correo','reemplazado')),
        cancellation_reason TEXT,
        approved_by INTEGER,
        approved_at TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES docx_templates(id) ON DELETE CASCADE,
        FOREIGN KEY(version_id) REFERENCES docx_template_versions(id) ON DELETE SET NULL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_docx_templates_scope
        ON docx_templates(brand, module, is_published, is_active);
    CREATE INDEX IF NOT EXISTS idx_docx_template_versions_current
        ON docx_template_versions(template_id, is_current, uploaded_at);
    CREATE INDEX IF NOT EXISTS idx_docx_template_fields_lookup
        ON docx_template_fields(version_id, variable_name);
    CREATE INDEX IF NOT EXISTS idx_docx_generated_scope
        ON docx_generated_documents(brand, station_id, template_id, status, created_at);
    """)

    for tbl, prefix in [
        ("alerts", "ALT"),
        ("maintenance", "MNT"),
        ("payments", "PAY"),
        ("documents", "DOC"),
        ("evidence_photos", "EVI"),
        ("notifications", "NOT"),
        ("submissions", "ACT"),
        ("doc_submissions", "DCS"),
        ("incident_logs", "INC"),
        ("correction_tasks", "TAS"),
        ("tramites", "TRA"),
        ("normativas", "NOR"),
        ("expediente_records", "EXP"),
    ]:
        try:
            ensure_column(conn, tbl, "folio", "folio TEXT")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_folio ON {tbl}(brand, folio)")
            conn.execute(
                f"UPDATE {tbl} SET folio=(? || '-' || strftime('%Y%m%d','now') || '-' || printf('%06d', id)) WHERE (folio IS NULL OR TRIM(folio)='')",
                (prefix,),
            )
        except Exception:
            pass

    for tbl in ['tramites', 'normativas', 'expediente_records']:
        try:
            ensure_column(conn, tbl, 'renewable', 'renewable INTEGER NOT NULL DEFAULT 1')
        except Exception:
            pass
        try:
            ensure_column(conn, tbl, 'periodicity', 'periodicity TEXT')
        except Exception:
            pass
        try:
            ensure_column(conn, tbl, 'reminder_days', "reminder_days TEXT NOT NULL DEFAULT '60,30,15,7,3,1,0'")
        except Exception:
            pass
        try:
            ensure_column(conn, tbl, 'last_renewal_date', 'last_renewal_date TEXT')
        except Exception:
            pass
    try:
        ensure_column(conn, 'expediente_records', 'responsible_user_id', 'responsible_user_id INTEGER')
    except Exception:
        pass

    # One-time bump: rows with the legacy default reminder_days get the 60-day notice added.
    # Custom values set by users are preserved.
    for tbl in ('tramites', 'normativas', 'expediente_records', 'document_deadlines'):
        try:
            conn.execute(
                f"UPDATE {tbl} SET reminder_days='60,30,15,7,3,1,0' WHERE reminder_days='30,15,7,3,1,0'"
            )
        except Exception:
            pass
        # SQLite keeps the original column DEFAULT clause in the table DDL; we cannot change
        # it without recreating the table. A trigger catches any future INSERT that lands
        # on the legacy default and bumps it forward.
        try:
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{tbl}_reminder_days_bump "
                f"AFTER INSERT ON {tbl} FOR EACH ROW WHEN NEW.reminder_days='30,15,7,3,1,0' "
                f"BEGIN UPDATE {tbl} SET reminder_days='60,30,15,7,3,1,0' WHERE id=NEW.id; END;"
            )
        except Exception:
            pass

    # SQLite triggers to assign folios automatically on insert
    trigger_map = {
        "alerts": "ALT",
        "maintenance": "MNT",
        "payments": "PAY",
        "documents": "DOC",
        "evidence_photos": "EVI",
        "notifications": "NOT",
        "submissions": "ACT",
        "doc_submissions": "DCS",
        "incident_logs": "INC",
        "correction_tasks": "TAS",
        "tramites": "TRA",
        "normativas": "NOR",
        "expediente_records": "EXP",
    }
    for tbl, prefix in trigger_map.items():
        try:
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{tbl}_folio AFTER INSERT ON {tbl} "
                f"FOR EACH ROW WHEN NEW.folio IS NULL OR TRIM(NEW.folio)='' BEGIN "
                f"UPDATE {tbl} SET folio='{prefix}-' || strftime('%Y%m%d','now') || '-' || printf('%06d', NEW.id) WHERE id=NEW.id; END;"
            )
        except Exception:
            pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_branding_settings ON branding_settings(brand, key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incident_scope ON incident_logs(brand, station_id, status, severity, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_correction_scope ON correction_tasks(brand, station_id, status, due_date, priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_drawn_signatures_scope ON drawn_signatures(brand, entity, entity_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_help_articles_scope ON help_articles(brand, category, is_featured, sort_order)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tramites_scope ON tramites(brand, station_id, status, due_date, priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_normative_catalog_scope ON normative_catalog(brand, category, is_active, sort_order)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_normativas_scope ON normativas(brand, station_id, status, next_due_date, risk_level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_templates_scope ON expediente_templates(brand, area, is_active, sort_order)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_records_scope ON expediente_records(brand, area, station_id, owner_name, status, expiry_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expediente_versions_record ON expediente_versions(record_id, version_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_deadlines_scope ON document_deadlines(brand, due_date, module, station_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_deadlines_responsible ON document_deadlines(brand, responsible_user_id, due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_deadline_notifications_unique ON deadline_notifications_log(deadline_id, user_id, notice_key, channel)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_renewal_history_scope ON document_renewal_history(brand, source_table, source_id, created_at)")
    except Exception:
        pass

    cur.execute("SELECT COUNT(*) AS c FROM help_articles")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            "INSERT INTO help_articles (brand, category, title, body, is_featured, sort_order) VALUES (?,?,?,?,?,?)",
            [
                ('consulting', 'Acceso', '¿Cómo inicio sesión?', 'Usa tu usuario y contraseña. Si eres admin, después eliges empresa desde el selector. Si eres operador o jefe, entras directo a tu panel según permisos.', 1, 10),
                ('consulting', 'Documentos', '¿Cómo subo documentos?', 'Ve al módulo correspondiente, captura o adjunta el archivo y confirma el envío. Los documentos con control requieren revisión y quedan auditados.', 1, 20),
                ('consulting', 'Notificaciones', '¿Cómo llegan las alertas?', 'Las alertas llegan dentro del sistema y también por correo. Si está configurado, también pueden salir por webhook de WhatsApp.', 0, 30),
                ('petroleum', 'Cumplimiento', '¿Qué muestra el semáforo?', 'Resume alertas, pagos, pendientes documentales y próximos vencimientos para cada estación.', 1, 10),
                ('petroleum', 'Documentos', '¿Cómo veo versiones y comparaciones?', 'Desde el centro documental puedes revisar historial, comparar versiones y restaurar la versión necesaria.', 1, 20),
                ('petroleum', 'Soporte', '¿Dónde veo ayuda rápida?', 'En el centro de ayuda encuentras preguntas frecuentes, enlaces oficiales y pasos de operación por módulo.', 0, 30),
            ],
        )
    try:
        # Defaults for branding keys so the wizard can edit them later.
        defaults = {
            'consulting': {
                'display_name': 'Consulting Oil & Gas',
                'subtitle': 'Renewable Energy HME, S.A. de C.V.',
                'system_title': 'CONSULTING • Work Log',
                'system_subtitle': 'Plataforma corporativa para estaciones',
                'primary_color': '#86B821',
                'secondary_color': '#2C7BE5',
                'public_url': 'https://consultinghme.com/',
                'hero_title': 'Sistema Corporativo de Gestión y Cumplimiento',
                'hero_text': 'Plataforma interna para la gestión operativa, cumplimiento normativo y control documental de estaciones y proyectos energéticos.',
            },
            'petroleum': {
                'display_name': 'Petroleum IU',
                'subtitle': 'Oil & Gas Inspection Unit',
                'system_title': 'PETROLEUM • Work Log',
                'system_subtitle': 'Oil & Gas Inspection Unit',
                'primary_color': '#C8A24A',
                'secondary_color': '#7C3AED',
                'public_url': 'https://petroleumiu.com/',
                'hero_title': 'Sistema Corporativo de Gestión y Cumplimiento',
                'hero_text': 'Plataforma interna para la gestión operativa, cumplimiento normativo y control documental de estaciones y proyectos energéticos.',
            },
        }
        for brand_key, settings in defaults.items():
            for key, value in settings.items():
                conn.execute(
                    "INSERT OR IGNORE INTO branding_settings (brand, key, value) VALUES (?,?,?)",
                    (brand_key, key, value),
                )
    except Exception:
        pass


    conn.commit()

    # Helpful indices (safe to run repeatedly)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_scope ON notifications(brand, station_id, user_id, is_read, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_events_scope ON calendar_events(brand, station_id, start_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_scope ON submissions(brand, station_id, event_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_scope ON payments(brand, station_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_group ON documents(brand, group_key, is_current, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_versions_group ON document_versions(brand, doc_group_key, version_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_station_access ON user_station_access(brand, user_id, station_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_internal_signatures_scope ON internal_signatures(brand, entity, entity_id, signed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_photos_scope ON evidence_photos(brand, entity, entity_id, station_id, created_at)")
    except Exception:
        pass


    # Ensure schema upgrades (safe ALTER ADD COLUMN)
    ensure_column(conn, "submissions", "signature_name", "signature_name TEXT")
    ensure_column(conn, "submissions", "signature_ip", "signature_ip TEXT")
    ensure_column(conn, "submissions", "signature_at", "signature_at TEXT")
    ensure_column(conn, "submissions", "signature_role", "signature_role TEXT")

    ensure_column(conn, "activities", "manual_path", "manual_path TEXT")
    ensure_column(conn, "activities", "manual_name", "manual_name TEXT")
    ensure_column(conn, "activities", "extra_path", "extra_path TEXT")
    ensure_column(conn, "activities", "extra_name", "extra_name TEXT")
    ensure_column(conn, "activities", "recurrence", "recurrence TEXT")
    ensure_column(conn, "activities", "target_station_id", "target_station_id INTEGER")

    # Petroleum Agenda runs on independent agenda_* tables, so keep those schema upgrades in sync too.
    ensure_column(conn, "agenda_activities", "manual_path", "manual_path TEXT")
    ensure_column(conn, "agenda_activities", "manual_name", "manual_name TEXT")
    ensure_column(conn, "agenda_activities", "extra_path", "extra_path TEXT")
    ensure_column(conn, "agenda_activities", "extra_name", "extra_name TEXT")
    ensure_column(conn, "agenda_activities", "recurrence", "recurrence TEXT")
    ensure_column(conn, "agenda_activities", "target_station_id", "target_station_id INTEGER")

    ensure_column(conn, "agenda_submissions", "signature_name", "signature_name TEXT")
    ensure_column(conn, "agenda_submissions", "signature_ip", "signature_ip TEXT")
    ensure_column(conn, "agenda_submissions", "signature_at", "signature_at TEXT")
    ensure_column(conn, "agenda_submissions", "signature_role", "signature_role TEXT")

    # Apply versioned migrations (ISO-friendly)
    try:
        _apply_versioned_migrations(conn)
    except Exception:
        pass

    # Seed initial admin only (clean install, no demo data)
    cur.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'")
    if cur.fetchone()["c"] == 0:
        admin_user = (os.environ.get("COG_ADMIN_USER") or "admin").strip() or "admin"
        admin_pass = os.environ.get("COG_ADMIN_PASS") or "admin123"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, station_id, allowed_brands, primary_brand) VALUES (?,?,?,NULL,?,?)",
            (admin_user, generate_password_hash(admin_pass), "admin", "consulting,petroleum", "consulting"),
        )
        conn.commit()

    # Precarga de actividades base para Consulting (programa preventivo anual)
    try:
        _seed_consulting_preloaded_activities_window(conn, years_ahead=5)
    except Exception:
        pass

        # Optional seed: SASISOPA document templates from bundled PDFs
    if os.environ.get("COG_SEED_TEMPLATES", "0") == "1":
        # Seed SASISOPA document templates from bundled PDFs (Consulting / Enero 2026)
        try:
            template_root = os.path.join(BASE_DIR, "uploads", "sasisopa_templates", "consulting")
            if os.path.isdir(template_root):
                for month_key in sorted(os.listdir(template_root)):
                    month_dir = os.path.join(template_root, month_key)
                    if not os.path.isdir(month_dir):
                        continue
                    for fname in sorted(os.listdir(month_dir)):
                        if not fname.lower().endswith('.pdf'):
                            continue
                        rel_path = os.path.join("sasisopa_templates", "consulting", month_key, fname).replace('\\', '/')
                        cur.execute("SELECT id FROM doc_templates WHERE brand='consulting' AND module='sasisopa' AND file_path=?", (rel_path,))
                        if cur.fetchone():
                            continue
                        cur.execute(
                            "INSERT INTO doc_templates (brand, module, name, file_path, month_key, field_schema_json, is_published, created_by) VALUES (?,?,?,?,?,?,?,NULL)",
                            ('consulting', 'sasisopa', os.path.splitext(fname)[0], rel_path, month_key, '[]', 0),
                        )
                conn.commit()
        except Exception:
            pass

    
# Seed Petroleum compliance items (safe; only if empty)
    cur.execute("SELECT COUNT(*) AS c FROM compliance_items")
    if cur.fetchone()["c"] == 0:
        items = [
            ("station_info", "Datos de estación (Razón social / Permiso / No. estación)", "Captura o documento que respalde razón social, número de permiso y número de estación.", "Identificación", 10),
            ("nom_005", "NOM-005", "Documentación y evidencias relacionadas con NOM-005.", "Normatividad", 20),
            ("nom_016", "NOM-016", "Documentación y evidencias relacionadas con NOM-016.", "Normatividad", 30),
            ("anexo_30_31", "ANEXO 30-31", "Evidencias y archivos de Anexo 30-31.", "Normatividad", 40),
            ("muestreos", "Muestreos", "Registros, resultados y evidencias de muestreos.", "Operación", 50),
            ("auditoria_sasisopa", "Auditoría SASISOPA", "Reportes, actas y evidencias de auditoría SASISOPA.", "SASISOPA", 60),
            ("dictaminacion_sasisopa", "Dictaminación SASISOPA", "Dictámenes, resolutivos y evidencias de dictaminación.", "SASISOPA", 70),
            ("doc_left", "Documento soporte (izquierda)", "Documento adicional relacionado al cumplimiento.", "Documentos", 80),
            ("doc_right_top", "Documento soporte (derecha superior)", "Documento adicional relacionado al cumplimiento.", "Documentos", 90),
            ("doc_right_bottom", "Documento soporte (derecha inferior)", "Documento adicional relacionado al cumplimiento.", "Documentos", 100),
        ]
        cur.executemany(
            "INSERT INTO compliance_items (code, title, description, section, sort_order) VALUES (?,?,?,?,?)",
            items,
        )
        conn.commit()


    cur.execute("SELECT COUNT(*) AS c FROM normative_catalog")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            "INSERT INTO normative_catalog (brand, code, title, category, description, periodicity, default_risk, sort_order, is_active) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ('petroleum', 'nom005', 'NOM-005', 'Seguridad', 'Control de seguridad y operación relacionado con NOM-005.', 'mensual', 'alto', 10, 1),
                ('petroleum', 'nom016', 'NOM-016', 'Documentacion legal', 'Verificación documental y técnica de NOM-016.', 'trimestral', 'alto', 20, 1),
                ('petroleum', 'anexo3031', 'Anexo 30-31', 'Verificaciones', 'Seguimiento de anexos y evidencias regulatorias.', 'mensual', 'medio', 30, 1),
                ('petroleum', 'muestreos', 'Muestreos', 'Ambiental', 'Muestreos, resultados y carga de evidencia.', 'mensual', 'medio', 40, 1),
                ('petroleum', 'auditoria_sasisopa', 'Auditoria SASISOPA', 'Inspeccion', 'Auditorias, observaciones y cierre de hallazgos.', 'anual', 'critico', 50, 1),
                ('petroleum', 'dictamen', 'Dictaminacion', 'Documentacion legal', 'Dictámenes, resolutivos y documentación soporte.', 'anual', 'alto', 60, 1),
            ],
        )
        conn.commit()

    cur.execute("SELECT COUNT(*) AS c FROM expediente_templates")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            "INSERT INTO expediente_templates (brand, area, code, title, description, is_required, default_validity_days, sort_order, is_active) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ('consulting', 'tramites', 'acta_constitutiva', 'Acta constitutiva', 'Documento base del cliente o razón social.', 1, 3650, 10, 1),
                ('consulting', 'tramites', 'constancia_fiscal', 'Constancia de situación fiscal', 'Constancia fiscal vigente del cliente.', 1, 365, 20, 1),
                ('consulting', 'tramites', 'identificacion_representante', 'Identificación del representante', 'INE o identificación oficial del responsable.', 1, 1095, 30, 1),
                ('consulting', 'tramites', 'permiso_operativo', 'Permiso / licencia operativa', 'Permiso, licencia o resolución asociada al trámite.', 1, 365, 40, 1),
                ('consulting', 'tramites', 'comprobante_domicilio', 'Comprobante de domicilio', 'Comprobante reciente del cliente o instalación.', 0, 180, 50, 1),
                ('consulting', 'tramites', 'contrato_servicio', 'Contrato / carta de servicio', 'Soporte contractual del servicio o gestión.', 0, 730, 60, 1),
                ('petroleum', 'normativas', 'permiso_cre', 'Permiso CRE / título aplicable', 'Documento legal base de la estación o permiso vigente.', 1, 365, 10, 1),
                ('petroleum', 'normativas', 'poliza_seguro', 'Póliza de seguro vigente', 'Cobertura de responsabilidad civil y riesgos aplicables.', 1, 365, 20, 1),
                ('petroleum', 'normativas', 'programa_mantenimiento', 'Programa de mantenimiento', 'Programa y evidencia de mantenimiento preventivo.', 1, 180, 30, 1),
                ('petroleum', 'normativas', 'bitacora_operacion', 'Bitácora de operación', 'Registros operativos actualizados.', 1, 30, 40, 1),
                ('petroleum', 'normativas', 'capacitacion_seguridad', 'Constancias de capacitación', 'Capacitaciones del personal y seguridad.', 1, 365, 50, 1),
                ('petroleum', 'normativas', 'dictamen_electrico', 'Dictamen / verificación técnica', 'Dictámenes técnicos, eléctricos o de inspección.', 0, 365, 60, 1),
            ],
        )
        conn.commit()

    # Enforce: only ONE saved final document per station (per module), overwriting previous.
    # If older DBs had multiple records per station/template, we keep the latest (by id).
    try:
        cur.execute(
            "DELETE FROM doc_records "
            "WHERE station_id IS NOT NULL AND id NOT IN ("
            "  SELECT MAX(id) FROM doc_records WHERE station_id IS NOT NULL GROUP BY brand, module, station_id"
            ")"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_records_station "
            "ON doc_records(brand, module, station_id) WHERE station_id IS NOT NULL"
        )
        conn.commit()
    except Exception:
        pass
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS public_quote_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        company TEXT,
        phone TEXT NOT NULL,
        contact_email TEXT,
        service_interest TEXT NOT NULL,
        details TEXT NOT NULL,
        source_page TEXT,
        ip_address TEXT,
        user_agent TEXT,
        email_delivery_status TEXT NOT NULL DEFAULT 'stored',
        email_delivery_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_public_quote_requests_created_at ON public_quote_requests(created_at);
    """)
    try:
        ensure_column(conn, "public_quote_requests", "source_page", "source_page TEXT")
        ensure_column(conn, "public_quote_requests", "ip_address", "ip_address TEXT")
        ensure_column(conn, "public_quote_requests", "user_agent", "user_agent TEXT")
        ensure_column(conn, "public_quote_requests", "email_delivery_status", "email_delivery_status TEXT NOT NULL DEFAULT 'stored'")
        ensure_column(conn, "public_quote_requests", "email_delivery_error", "email_delivery_error TEXT")
    except Exception:
        pass

    # Close connection at end of init_db()
    conn.close()


def verify_user(username: str, password: str, *, ip: str | None = None):
    """Verify user credentials with per-user lockout.

    Returns: (user_dict, error_code)
      - error_code: None when success, else one of:
        'invalid_credentials', 'user_locked', 'user_inactive'
    """
    import time
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None, "invalid_credentials"
    if int(row.get("is_active") or 0) != 1:
        conn.close()
        return None, "user_inactive"

    now = int(time.time())
    locked_until = row.get("locked_until")
    try:
        locked_until = int(locked_until) if locked_until is not None and str(locked_until).strip() != "" else 0
    except Exception:
        locked_until = 0
    if locked_until and locked_until > now:
        conn.close()
        return None, "user_locked"

    ok = False
    try:
        ok = check_password_hash(row["password_hash"], password)
    except Exception:
        ok = False

    if ok:
        try:
            cur.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            conn.commit()
        except Exception:
            pass
        user = dict(row)
        conn.close()
        return user, None

    threshold = int(os.environ.get("COG_LOCK_THRESHOLD", "5") or 5)
    minutes = int(os.environ.get("COG_LOCK_MINUTES", "15") or 15)

    try:
        fails = int(row.get("failed_attempts") or 0) + 1
    except Exception:
        fails = 1

    lock_until = None
    if fails >= threshold:
        lock_until = now + minutes * 60
        fails = 0

    try:
        cur.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (fails, lock_until, row["id"]))
        conn.commit()
    except Exception:
        pass

    conn.close()
    return None, "invalid_credentials"

def get_user(user_id: int):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT u.*, s.monthly_status, s.monthly_end FROM users u LEFT JOIN stations s ON s.id=u.station_id WHERE u.id=?",
        (user_id,),
    )
    row = cur.fetchone(); conn.close()
    return dict(row) if row else None
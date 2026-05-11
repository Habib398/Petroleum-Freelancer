"""DOCX template variable catalog and resolver.

This module owns the mapping between the variable names that admins write inside
their Word templates (e.g. ``<<NOMBRE_ESTACION>>``) and the actual data sources
inside the application (the ``stations`` row, the ``station_profiles`` row, or
system-provided values such as today's date).

Design notes
------------
* Variables are matched **case-insensitively**: ``<<rfc>>``, ``<<RFC>>`` and
  ``<<Rfc>>`` all resolve the same way. The canonical form is uppercase.
* If a detected variable is not in the catalog, it is classified as ``manual``
  by default. Admin can later flip it to ``fixed`` or wire it to a custom
  source via the field-config UI.
* The resolver returns ``None`` for variables that exist in the catalog but
  whose underlying field is empty in the DB. The render step decides whether
  to leave the placeholder empty or surface a warning.
* This catalog is the source of truth for the DOCX engine. The legacy PDF
  engine in ``modules/compliance/documental_docs.py`` is unaffected.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable

from db import get_conn


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
#
# Each entry maps a canonical variable name to a triple:
#   (source, source_key, kind)
#
# - ``source``   : "station" | "station_profile" | "system"
# - ``source_key``: the column or system key to read
# - ``kind``     : "text" | "image" | "date_today"
#
# Adding a new auto-resolved variable is just a matter of appending an entry
# here and (if needed) ensuring the underlying column exists in the DB.

KNOWN_VARIABLES: dict[str, tuple[str, str, str]] = {
    # Station identity
    "NOMBRE_ESTACION":       ("station", "name",            "text"),
    "NUMERO_ESTACION":       ("station", "station_number",  "text"),
    "CODIGO_ESTACION":       ("station", "code",            "text"),
    "GRUPO_ESTACION":        ("station", "group_name",      "text"),
    "ESTADO_ESTACION":       ("station", "state",           "text"),
    "CIUDAD_ESTACION":       ("station", "city",            "text"),
    "DIRECCION_ESTACION":    ("station", "address",         "text"),

    # Station private data (admin-only fields populated via /api/profile)
    "RAZON_SOCIAL":          ("station_profile", "legal_name",            "text"),
    "RFC":                   ("station_profile", "rfc",                   "text"),
    "DOMICILIO":             ("station_profile", "domicilio",             "text"),
    "PERMISO_CRE":           ("station_profile", "permiso_cre",           "text"),
    "PERMISO_NUMERO":        ("station_profile", "permit_number",         "text"),
    "REPRESENTANTE_LEGAL":   ("station_profile", "representante_legal",   "text"),
    "RESPONSABLE_OPERATIVO": ("station_profile", "responsable_operativo", "text"),
    "RESPONSABLE_SASISOPA":  ("station_profile", "responsable_sasisopa",  "text"),
    "RESPONSABLE_SGM":       ("station_profile", "responsable_sgm",       "text"),
    "CORREO_ESTACION":       ("station_profile", "correo",                "text"),
    "TELEFONO_ESTACION":     ("station_profile", "telefono",              "text"),

    # Logos (resolved as image paths; the render step inserts the picture)
    "LOGO_EMPRESA":          ("station_profile", "logo_empresa_path",     "image"),
    "LOGO_ESTACION":         ("station_profile", "logo_estacion_path",    "image"),

    # System-provided
    "FECHA_HOY":             ("system", "today",      "date_today"),
    "FECHA_ACTUAL":          ("system", "today",      "date_today"),
    "FECHA_HORA":            ("system", "now",        "date_today"),
    "ANIO_ACTUAL":           ("system", "year",       "text"),
    "MES_ACTUAL":            ("system", "month_name", "text"),
}


# Spanish month names (system-resolved variables use these for FECHA_HOY etc.)
_MONTH_NAMES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def canonical(name: str) -> str:
    """Normalize a variable name to its canonical form (uppercase, stripped)."""
    return (name or "").strip().upper()


def is_known(name: str) -> bool:
    return canonical(name) in KNOWN_VARIABLES


def classify(name: str) -> str:
    """Return the suggested ``field_kind`` for a freshly detected variable.

    - Known text/data variables  -> ``auto``
    - Known image variables      -> ``image``
    - Known system date/time     -> ``date_today``
    - Anything else              -> ``manual``
    """
    entry = KNOWN_VARIABLES.get(canonical(name))
    if not entry:
        return "manual"
    _, _, kind = entry
    if kind == "image":
        return "image"
    if kind == "date_today":
        return "date_today"
    return "auto"


def auto_source_for(name: str) -> str | None:
    """Return a stable string identifying the data source for a known variable.

    Format: ``"<source>.<source_key>"`` (e.g. ``"station.name"``,
    ``"station_profile.rfc"``). Returned value is what gets stored in
    ``docx_template_fields.auto_source``.
    """
    entry = KNOWN_VARIABLES.get(canonical(name))
    if not entry:
        return None
    source, source_key, _ = entry
    return f"{source}.{source_key}"


def label_for(name: str) -> str:
    """Generate a human-readable label from a variable name.

    ``<<NOMBRE_ESTACION>>`` -> ``"Nombre estacion"``. The UI will replace this
    with whatever admin types in the field-config form.
    """
    n = canonical(name)
    if not n:
        return ""
    return n.replace("_", " ").capitalize()


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def _fetch_station_row(conn, station_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM stations WHERE id=?", (int(station_id),))
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_station_profile_row(conn, station_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM station_profiles WHERE station_id=?", (int(station_id),))
    row = cur.fetchone()
    return dict(row) if row else None


def _system_value(key: str) -> Any:
    today = datetime.date.today()
    now = datetime.datetime.now()
    if key == "today":
        return today.isoformat()
    if key == "now":
        return now.isoformat(timespec="seconds")
    if key == "year":
        return str(today.year)
    if key == "month_name":
        return _MONTH_NAMES_ES[today.month - 1]
    return None


def resolve_auto_values(station_id: int | None, *, conn=None) -> dict[str, Any]:
    """Resolve every auto-fillable variable for a given station.

    Returns a dict keyed by canonical variable name. Variables whose underlying
    field is empty in the DB are included with value ``None`` so the caller can
    distinguish "not set" from "not requested".

    A connection can be passed in for transactional reuse; otherwise a new one
    is opened and closed.
    """
    own_conn = False
    if conn is None:
        conn = get_conn()
        own_conn = True

    station_row: dict | None = None
    profile_row: dict | None = None
    if station_id:
        station_row = _fetch_station_row(conn, station_id)
        profile_row = _fetch_station_profile_row(conn, station_id)

    out: dict[str, Any] = {}
    for var, (source, source_key, _kind) in KNOWN_VARIABLES.items():
        value: Any = None
        if source == "station" and station_row is not None:
            value = station_row.get(source_key)
        elif source == "station_profile" and profile_row is not None:
            value = profile_row.get(source_key)
        elif source == "system":
            value = _system_value(source_key)

        if value == "":
            value = None
        out[var] = value

    if own_conn:
        conn.close()
    return out


def resolve_one(name: str, station_id: int | None, *, conn=None) -> Any:
    """Resolve a single variable. Returns ``None`` if unknown or empty."""
    cname = canonical(name)
    entry = KNOWN_VARIABLES.get(cname)
    if not entry:
        return None
    return resolve_auto_values(station_id, conn=conn).get(cname)


def merge_with_manual(auto_values: dict[str, Any], manual_values: dict[str, Any]) -> dict[str, Any]:
    """Merge auto-resolved values with manual user-provided values.

    Manual values take precedence (useful when admin overrides an auto value
    for one specific document). Empty strings in ``manual_values`` are treated
    as "leave the auto value alone".
    """
    out = dict(auto_values or {})
    for key, val in (manual_values or {}).items():
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        out[canonical(key)] = val
    return out


def list_known() -> list[dict]:
    """Catalog dump for admin UIs (selectors, help screens, etc.)."""
    out: list[dict] = []
    for var, (source, source_key, kind) in sorted(KNOWN_VARIABLES.items()):
        out.append({
            "variable": var,
            "source": source,
            "source_key": source_key,
            "kind": kind,
            "auto_source": f"{source}.{source_key}",
            "label": label_for(var),
        })
    return out


def filter_unknown(detected: Iterable[str]) -> list[str]:
    """Given a list of detected variables, return those NOT in the catalog."""
    return [v for v in detected if not is_known(v)]

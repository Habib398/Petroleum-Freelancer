"""
services/utils.py
-----------------
Utilidades compartidas entre módulos.

Centraliza helpers de uso común para evitar duplicación de código
(violación DRY) que antes existía dispersa en scheduled.py, activities.py,
extras.py y db.py.
"""

from __future__ import annotations

import datetime


# ---------------------------------------------------------------------------
# Aritmética de fechas
# ---------------------------------------------------------------------------

def add_months(d: datetime.date, months: int) -> datetime.date:
    """Avanza una fecha exactamente N meses.

    Si el día resultante no existe en el mes destino (p. ej. 31 de enero + 1 mes),
    se ajusta al último día válido del mes.

    Ejemplos:
        add_months(date(2024, 1, 31), 1)  -> date(2024, 2, 29)  (año bisiesto)
        add_months(date(2024, 1, 31), 1)  -> date(2025, 2, 28)  (año normal)
        add_months(date(2024, 3, 15), 3)  -> date(2024, 6, 15)
    """
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # Último día del mes destino
    if m == 12:
        last_day = datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last_day = datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)
    return datetime.date(y, m, min(d.day, last_day.day))


def parse_iso_date(value: str | None, default: datetime.date) -> datetime.date:
    """Parsea una cadena ISO-8601 a `datetime.date`, con fallback seguro.

    Acepta formatos como '2024-06-15' o '2024-06-15T10:30:00Z'.
    Retorna `default` si el valor es None, vacío o tiene formato inválido.
    """
    if not value:
        return default
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Helpers de red / request
# ---------------------------------------------------------------------------

def get_client_ip(request) -> str:
    """Extrae la IP real del cliente considerando proxies (X-Forwarded-For).

    Retorna 'unknown' si no se puede determinar la IP.
    Toma solo el primer IP de la cadena X-Forwarded-For para evitar
    que un cliente malicioso inyecte IPs falsas al final.
    """
    forwarded = request.headers.get("X-Forwarded-For") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return (request.remote_addr or "unknown").strip() or "unknown"


# ---------------------------------------------------------------------------
# Helpers de parsing de payloads
# ---------------------------------------------------------------------------

def strip_field(data: dict, key: str, default: str = "") -> str:
    """Extrae y limpia un campo de texto de un diccionario (p. ej. payload JSON).

    Equivalente al patrón repetido: `(data.get("key") or "").strip()`
    """
    return (data.get(key) or default).strip()


# ---------------------------------------------------------------------------
# Construcción de cláusulas SQL dinámicas
# ---------------------------------------------------------------------------

def build_in_clause(values: list) -> tuple[str, list]:
    """Construye un fragmento SQL `IN (?,?,?)` con sus parámetros.

    Centraliza el patrón repetido en múltiples módulos:
        q = ",".join(["?"] * len(scope))
        cur.execute(f"... WHERE id IN ({q})", tuple(scope))

    Uso:
        clause, params = build_in_clause(station_ids)
        cur.execute(f"SELECT * FROM stations WHERE id {clause}", params)

    Si la lista está vacía retorna ("IN (NULL)", []) para que la query
    no falle con sintaxis inválida `IN ()`.
    """
    if not values:
        return "IN (NULL)", []
    placeholders = ",".join(["?"] * len(values))
    return f"IN ({placeholders})", list(values)

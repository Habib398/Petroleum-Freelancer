"""
services/state.py
-----------------
Lectura y escritura del estado interno del sistema (tabla `system_state`).

Centraliza las funciones `_get_state` / `_set_state` que antes estaban
duplicadas (con interfaces ligeramente diferentes) en:
  - modules/core/extras.py
  - services/scheduled.py
"""

from __future__ import annotations


def get_state(conn, key: str) -> str:
    """Lee el valor asociado a `key` en la tabla `system_state`.

    Retorna una cadena vacía si la clave no existe o si el valor es NULL.
    Nunca lanza excepción para evitar interrumpir flujos de usuario.
    """
    try:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return ""
        value = row["value"] if hasattr(row, "__getitem__") else row[0]
        return (value or "")
    except Exception:
        return ""


def set_state(conn, key: str, value: str) -> None:
    """Escribe o actualiza el valor de `key` en `system_state` (upsert).

    Usa `ON CONFLICT DO UPDATE` para que sea idempotente: si la clave ya
    existe la sobreescribe, si no existe la inserta.
    No hace `conn.commit()` — el llamador es responsable de la transacción,
    lo que permite agrupar varias escrituras en un solo commit.
    """
    conn.execute(
        "INSERT INTO system_state (key, value, updated_at)"
        " VALUES (?, ?, CURRENT_TIMESTAMP)"
        " ON CONFLICT(key) DO UPDATE"
        " SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        (key, value),
    )

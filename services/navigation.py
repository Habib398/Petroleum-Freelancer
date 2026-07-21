"""
services/navigation.py
----------------------
Lógica de navegación: mapea el path del request a la sección activa del sidebar.

Extraído de app.py (_get_active_section) para separar la responsabilidad
de navegación del archivo de configuración de la aplicación.
"""

from __future__ import annotations


# Mapeo exacto path -> sección del sidebar.
# Orden: de más específico a más general (se usa prefix-match como fallback).
_SECTION_MAP: dict[str, str] = {
    "/mod/pipas":                        "operacion_tecnica",
    "/mod/maintenance":                  "operacion_tecnica",
    "/mod/alerts":                       "operacion_tecnica",
    "/mod/reports":                      "operacion_tecnica",
    "/mod/payments":                     "operacion_tecnica",
    "/mod/activities":                   "operacion",
    "/mod/operational-calendar":         "operacion",
    "/mod/station-evidence":             "operacion",
    "/mod/document-renewals-calendar":   "operacion",
    "/mod/evidencias":                   "operacion",
    "/mod/incidents":                    "operacion",
    "/mod/corrections":                  "operacion",
    "/petroleum/normativas":             "normativa_control",
    "/petroleum/expedientes":            "normativa_control",
    "/mod/help-center":                  "ayuda",
    "/mod/signature-pad":               "ayuda",
    "/mod/analytics":                    "ayuda",
}


def get_active_section(path: str) -> str | None:
    """Retorna el nombre de la sección del sidebar correspondiente al `path`.

    Primero intenta match exacto; si no encuentra, intenta match por prefijo.
    Retorna None si el path no corresponde a ninguna sección conocida.
    """
    path = (path or "").lower()

    # Match exacto (más rápido y preciso)
    if path in _SECTION_MAP:
        return _SECTION_MAP[path]

    # Match por prefijo (para sub-rutas como /mod/activities/123)
    for route, section in _SECTION_MAP.items():
        if path.startswith(route.rstrip("/")):
            return section

    return None

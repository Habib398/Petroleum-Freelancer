# modules/petroleum/__init__.py
# Dominio: Funcionalidad exclusiva del sistema Petroleum IU.
# Incluye: rutas específicas de la marca Petroleum.

from routes.petroleum import register as register_petroleum


def register(app):
    register_petroleum(app)

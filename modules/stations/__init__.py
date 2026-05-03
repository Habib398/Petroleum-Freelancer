# modules/stations/__init__.py
# Dominio: Estaciones de servicio.
# Incluye: CRUD de estaciones, mapa, importación KML.

from modules.stations.routes import bp as stations_bp


def register(app):
    app.register_blueprint(stations_bp)

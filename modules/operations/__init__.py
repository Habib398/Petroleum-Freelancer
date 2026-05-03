# modules/operations/__init__.py
# Dominio: Operaciones diarias de las estaciones.
# Incluye: actividades/agenda, pipas, mantenimiento, alertas,
#          pagos, calibraciones y bitácoras.

from routes.activities import register as register_activities
from routes.pipas import register as register_pipas
from routes.maintenance import register as register_maintenance
from routes.alerts import register as register_alerts
from routes.payments import register as register_payments
from routes.calibraciones import register as register_calibraciones
from routes.bitacoras import register as register_bitacoras


def register(app):
    register_activities(app)
    register_pipas(app)
    register_maintenance(app)
    register_alerts(app)
    register_payments(app)
    register_calibraciones(app)
    register_bitacoras(app)

# modules/operations/__init__.py
# Dominio: Operaciones diarias de las estaciones.
# Incluye: actividades/agenda, pipas, mantenimiento, alertas,
#          pagos, calibraciones y bitácoras.

from modules.operations.activities import register as register_activities
from modules.operations.pipas import register as register_pipas
from modules.operations.maintenance import register as register_maintenance
from modules.operations.alerts import register as register_alerts
from modules.operations.payments import register as register_payments
from modules.operations.calibraciones import register as register_calibraciones
from modules.operations.bitacoras import register as register_bitacoras


def register(app):
    register_activities(app)
    register_pipas(app)
    register_maintenance(app)
    register_alerts(app)
    register_payments(app)
    register_calibraciones(app)
    register_bitacoras(app)

# modules/admin/__init__.py
# Dominio: Administración, analítica y reportes.
# Incluye: panel de admin, avanzados, reportes, exportaciones analíticas,
#          panel ejecutivo y organigrama.

from routes.admin import register as register_admin
from routes.advanced import register as register_advanced
from routes.reports import register as register_reports
from routes.analytics_exports import register as register_analytics
from routes.executive import register as register_executive
from routes.orgchart import register as register_orgchart


def register(app):
    register_admin(app)
    register_advanced(app)
    register_reports(app)
    register_analytics(app)
    register_executive(app)
    register_orgchart(app)

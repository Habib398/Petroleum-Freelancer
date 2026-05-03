# modules/core/__init__.py
# Dominio: Núcleo transversal de la aplicación.
# Incluye: páginas generales, uploads, notificaciones, tareas internas, respaldos y extras.

from routes.pages import register as register_pages
from routes.uploads import register as register_uploads
from routes.notifications import register as register_notifications
from routes.internal_tasks import register as register_internal_tasks
from routes.backup import register as register_backup
from routes.extras import register as register_extras


def register(app):
    register_pages(app)
    register_uploads(app)
    register_notifications(app)
    register_internal_tasks(app)
    register_backup(app)
    register_extras(app)

# modules/core/__init__.py
# Dominio: Núcleo transversal de la aplicación.
# Incluye: páginas generales, uploads, notificaciones, tareas internas, respaldos y extras.

from modules.core.pages import register as register_pages
from modules.core.uploads import register as register_uploads
from modules.core.notifications import register as register_notifications
from modules.core.internal_tasks import register as register_internal_tasks
from modules.core.backup import register as register_backup
from modules.core.extras import register as register_extras


def register(app):
    register_pages(app)
    register_uploads(app)
    register_notifications(app)
    register_internal_tasks(app)
    register_backup(app)
    register_extras(app)

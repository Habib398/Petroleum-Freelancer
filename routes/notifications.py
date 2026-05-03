# routes/notifications.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules.core.notifications
from modules.core.notifications import register

__all__ = ["register"]


# routes/backup.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules.core.backup
from modules.core.backup import register

__all__ = ["register"]


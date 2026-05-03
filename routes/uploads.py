# routes/uploads.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules.core.uploads
from modules.core.uploads import register

__all__ = ["register"]


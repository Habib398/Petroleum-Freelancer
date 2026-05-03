# routes/profile.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules/auth/profile.py
from modules.auth.profile import register

__all__ = ["register"]

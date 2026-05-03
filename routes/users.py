# routes/users.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules/auth/users.py
from modules.auth.users import register

__all__ = ["register"]

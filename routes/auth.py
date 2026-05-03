# routes/auth.py
# SHIM DE COMPATIBILIDAD — el código real vive en modules/auth/auth.py
# Este archivo existe para que los módulos que aún importan desde routes.auth
# (compliance.py, pages.py, petroleum.py) continúen funcionando sin cambios.

from modules.auth.auth import (
    login_required,
    role_required,
    register,
)

__all__ = ["login_required", "role_required", "register"]
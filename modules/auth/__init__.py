# modules/auth/__init__.py
# Dominio: Autenticación, usuarios y perfiles.
# Rutas: login, logout, password reset, gestión de usuarios, perfil.

# modules/auth/__init__.py
# Dominio: Autenticación, usuarios y perfiles.
# Rutas: login, logout, password reset, gestión de usuarios, perfil.

from modules.auth.auth import register as register_auth
from modules.auth.users import register as register_users
from modules.auth.profile import register as register_profile

# Re-exportar decoradores para compatibilidad con otros módulos
# (compliance.py, pages.py y petroleum.py importan desde aquí)
from modules.auth.auth import login_required, role_required


def register(app):
    register_auth(app)
    register_users(app)
    register_profile(app)

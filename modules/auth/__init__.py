# modules/auth/__init__.py
# Dominio: Autenticación, usuarios y perfiles.
# Rutas: login, logout, password reset, gestión de usuarios, perfil.

from routes.auth import register as register_auth
from routes.users import register as register_users
from routes.profile import register as register_profile


def register(app):
    register_auth(app)
    register_users(app)
    register_profile(app)

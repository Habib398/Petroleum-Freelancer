# routes/analytics_exports.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.admin.analytics_exports
from modules.admin.analytics_exports import register

__all__ = ["register"]


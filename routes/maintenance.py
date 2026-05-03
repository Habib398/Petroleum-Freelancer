# routes/maintenance.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.operations.maintenance
from modules.operations.maintenance import register

__all__ = ["register"]


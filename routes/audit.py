# routes/audit.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.compliance.audit
from modules.compliance.audit import register

__all__ = ["register"]


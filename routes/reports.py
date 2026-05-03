# routes/reports.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.admin.reports
from modules.admin.reports import register

__all__ = ["register"]


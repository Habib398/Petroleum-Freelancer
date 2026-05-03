# routes/orgchart.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.admin.orgchart
from modules.admin.orgchart import register

__all__ = ["register"]


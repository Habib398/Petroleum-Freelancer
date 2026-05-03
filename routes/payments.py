# routes/payments.py
# SHIM DE COMPATIBILIDAD -- el codigo real vive en modules.operations.payments
from modules.operations.payments import register

__all__ = ["register"]


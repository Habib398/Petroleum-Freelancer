from __future__ import annotations

import compileall
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

checks = []
checks.append((ROOT / 'app.py').exists())
checks.append((ROOT / 'db.py').exists())
checks.append((ROOT / 'requirements.txt').exists())
checks.append((ROOT / 'templates').exists())
checks.append((ROOT / 'static').exists())
checks.append((ROOT / 'data').exists())
checks.append((ROOT / '.env').exists())

syntax_ok = compileall.compile_dir(str(ROOT), quiet=1, force=True)

print('VERIFICACION PROYECTO')
print('---------------------')
print(f'Ruta: {ROOT}')
print(f'Archivos base: {"OK" if all(checks) else "FALTAN ARCHIVOS"}')
print(f'Sintaxis Python: {"OK" if syntax_ok else "ERROR"}')
print(f'Base de datos existe: {((ROOT / "data" / "cog_work_log.db").exists())}')
print(f'Uploads existe: {((ROOT / "uploads").exists())}')
print(f'Logs existe: {((ROOT / "logs").exists())}')
print('Listo para pruebas locales.' if all(checks) and syntax_ok else 'Revisar estructura del proyecto.')

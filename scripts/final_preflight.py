from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'cog_work_log.db'

def main() -> int:
    ap = argparse.ArgumentParser(description='Revisión final Work Log')
    ap.add_argument('--reset-public-quotes', action='store_true', help='Eliminar cotizaciones públicas de prueba')
    args = ap.parse_args()

    print('=== Work Log · revisión final ===')
    print(f'Raíz: {ROOT}')
    print(f'Base de datos: {DB}')
    print(f'Debug APP_DEBUG={os.environ.get("APP_DEBUG", "0")}')
    print(f'MAIL_PROVIDER={os.environ.get("MAIL_PROVIDER", os.environ.get("COG_MAIL_PROVIDER", "auto"))}')
    print(f'PUBLIC_QUOTE_RECIPIENTS={os.environ.get("PUBLIC_QUOTE_RECIPIENTS", "usiel54@hotmail.com,misaelsainz9@gmail.com")}')

    if not DB.exists():
        print('ERROR: No existe la base de datos.')
        return 1

    con = sqlite3.connect(DB)
    cur = con.cursor()
    tables = ['users','stations','activities','notifications','public_quote_requests']
    for t in tables:
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            print(f'{t}: {n}')
        except Exception as exc:
            print(f'{t}: error -> {exc}')

    if args.reset_public_quotes:
        cur.execute('DELETE FROM public_quote_requests')
        con.commit()
        try:
            cur.execute('VACUUM')
        except Exception:
            pass
        print('Cotizaciones públicas eliminadas.')

    con.close()
    print('Revisión terminada.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

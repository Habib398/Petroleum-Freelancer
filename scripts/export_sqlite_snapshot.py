from __future__ import annotations

import csv
import os
from pathlib import Path

from db import get_conn

OUT_DIR = Path(os.environ.get("EXPORT_OUT_DIR") or "exports/sqlite_snapshot")
OUT_DIR.mkdir(parents=True, exist_ok=True)

conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
tables = [r[0] if not isinstance(r, dict) else r["name"] for r in cur.fetchall()]

for table in tables:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    cols = []
    try:
        cols = list(rows[0].keys()) if rows else [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    path = OUT_DIR / f"{table}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(cols)
        for row in rows:
            if isinstance(row, dict):
                wr.writerow([row.get(c) for c in cols])
            else:
                wr.writerow(list(row))
print(f"Exportación lista en {OUT_DIR}")

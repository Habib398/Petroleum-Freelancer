"""
seed_compliance_demo.py — Inserta entregas aprobadas DE PRUEBA para que el
reporte de cumplimiento muestre valores no-cero.

Cada entrega creada por este script lleva notes='[DEMO_SEED]' para que sea
trivial revertirla con --undo.

Uso:
    # Sembrar solo hoy (~50% de actividades aprobadas)
    python scripts/seed_compliance_demo.py

    # Sembrar TODO el año actual con variación por mes para que las gráficas
    # mensual y semanal tengan historia visible
    python scripts/seed_compliance_demo.py --full

    # Cambiar brand o porcentaje base
    python scripts/seed_compliance_demo.py --brand petroleum --pct 70

    # Revertir TODO lo sembrado por este script
    python scripts/seed_compliance_demo.py --undo
"""
from __future__ import annotations

import argparse
import math
import random
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cog_work_log.db"
DEMO_MARK = "[DEMO_SEED]"


def open_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"BD no encontrada en {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def undo(brand: str | None) -> int:
    conn = open_conn()
    cur = conn.cursor()
    if brand:
        cur.execute("DELETE FROM submissions WHERE brand=? AND notes=?", (brand, DEMO_MARK))
    else:
        cur.execute("DELETE FROM submissions WHERE notes=?", (DEMO_MARK,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def list_stations(conn: sqlite3.Connection, brand: str) -> list[int]:
    cur = conn.cursor()
    cur.execute("SELECT id FROM stations WHERE brand=? ORDER BY id", (brand,))
    return [int(r["id"]) for r in cur.fetchall()]


def pct_for_month(base_pct: int, month: int) -> int:
    """% que varia por mes alrededor de base_pct para que la grafica se vea natural."""
    deltas = [-15, -8, +5, +12, +3, -10, +8, +15, +4, -6, +10, +18]
    val = base_pct + deltas[(month - 1) % 12]
    return max(5, min(95, val))


def seed(brand: str, base_pct: int, today_only: bool, seed_rng: int = 42) -> tuple[int, int]:
    rng = random.Random(seed_rng)
    conn = open_conn()
    cur = conn.cursor()

    stations = list_stations(conn, brand)
    if not stations:
        conn.close()
        return (0, 0)

    today = date.today()
    if today_only:
        from_d = today.isoformat()
        to_d = today.isoformat()
    else:
        from_d = date(today.year, 1, 1).isoformat()
        to_d = today.isoformat()

    cur.execute(
        "SELECT id, activity_id, station_id, start_date FROM calendar_events "
        "WHERE brand=? AND date(start_date) BETWEEN date(?) AND date(?)",
        (brand, from_d, to_d),
    )
    events = cur.fetchall()
    if not events:
        conn.close()
        return (0, 0)

    inserted = 0
    skipped = 0

    for ev in events:
        ev_id = ev["id"]
        act_id = ev["activity_id"]
        ev_station = ev["station_id"]
        try:
            ev_date = datetime.strptime(ev["start_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue

        target_pct = pct_for_month(base_pct, ev_date.month)

        # Para cada estación obligada (NULL => todas; específica => solo esa)
        target_stations = stations if ev_station is None else [int(ev_station)]
        for sid in target_stations:
            # ¿Ya hay submission (real o demo) para este (event, station)?
            cur.execute(
                "SELECT 1 FROM submissions WHERE brand=? AND event_id=? AND station_id=?",
                (brand, ev_id, sid),
            )
            if cur.fetchone():
                skipped += 1
                continue

            roll = rng.random() * 100.0
            if roll > target_pct:
                continue

            cur.execute(
                "INSERT INTO submissions "
                "(brand, event_id, activity_id, station_id, user_id, notes, evidence_path, "
                " status, score, review_notes, reviewed_by, created_at, reviewed_at, "
                " signature_name, signature_role) "
                "VALUES (?, ?, ?, ?, NULL, ?, '', 'approved', 100, 'Aprobado (demo)', NULL, ?, ?, 'DEMO', 'demo')",
                (brand, ev_id, act_id, sid, DEMO_MARK,
                 ev_date.isoformat() + " 12:00:00",
                 ev_date.isoformat() + " 18:00:00"),
            )
            inserted += 1

    conn.commit()
    conn.close()
    return (inserted, skipped)


def main():
    ap = argparse.ArgumentParser(description="Seed de cumplimiento para demo visual.")
    ap.add_argument("--brand", default="consulting", help="consulting | petroleum (default consulting)")
    ap.add_argument("--pct", type=int, default=50, help="% base de cumplimiento (default 50)")
    ap.add_argument("--full", action="store_true", help="Sembrar todo el año, no solo hoy.")
    ap.add_argument("--undo", action="store_true", help="Eliminar TODAS las entregas marcadas [DEMO_SEED].")
    args = ap.parse_args()

    if args.undo:
        # --brand opcional para limitar el undo a una marca
        target_brand = args.brand if "--brand" in __import__("sys").argv else None
        n = undo(target_brand)
        print(f"Eliminadas {n} entregas marcadas {DEMO_MARK}" + (f" (brand={target_brand})" if target_brand else " (todas las marcas)"))
        return

    ins, sk = seed(args.brand, args.pct, today_only=not args.full)
    print(f"Brand={args.brand}  base_pct={args.pct}  modo={'TODO_EL_AÑO' if args.full else 'HOY'}")
    print(f"Insertadas: {ins}   Saltadas (ya tenían submission): {sk}")
    print()
    print("Para revertir:  python scripts/seed_compliance_demo.py --undo")


if __name__ == "__main__":
    main()

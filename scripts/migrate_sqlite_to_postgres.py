#!/usr/bin/env python3
"""Best-effort migration from the bundled SQLite database to PostgreSQL.

Usage:
  export COG_DB_ENGINE=postgres
  export COG_DATABASE_URL=postgresql://user:pass@host:5432/worklog
  python scripts/migrate_sqlite_to_postgres.py --sqlite data/cog_work_log.db

Notes:
- Creates the PostgreSQL schema through db.init_db().
- Copies rows table by table and retries pending rows across multiple passes.
- Preserves primary key IDs when possible and then resets identities.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

DEFAULT_ORDER = [
    'stations', 'users', 'user_station_access',
    'activities', 'agenda_activities',
    'calendar_events', 'agenda_calendar_events',
    'submissions', 'agenda_submissions',
    'pumps', 'maintenance', 'payments', 'alerts', 'alert_templates', 'bitacoras', 'pipas',
    'branding_settings', 'help_articles', 'notification_keys', 'notifications', 'audit_log', 'password_resets', 'system_state',
    'petroleum_doc_types', 'petroleum_owner_catalog', 'petroleum_station_control', 'petroleum_norm_files',
    'compliance_records', 'compliance_items', 'compliance_files',
    'doc_templates', 'doc_records', 'doc_requirements', 'doc_submissions', 'doc_unlocks', 'documents', 'document_versions',
    'normative_catalog', 'normativas', 'tramites',
    'expediente_templates', 'expediente_records', 'expediente_versions',
    'document_deadlines', 'deadline_notifications_log', 'document_renewal_history',
    'incident_logs', 'correction_tasks', 'comments', 'drawn_signatures', 'internal_signatures',
    'capa_actions', 'cal_tanks', 'station_profiles', 'nonconformities',
    'org_charts', 'org_chart_nodes',
    'schema_migrations',
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sqlite', default='data/cog_work_log.db', help='Path to SQLite file')
    ap.add_argument('--max-passes', type=int, default=4, help='Retry passes for FK-dependent rows')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.exists():
        raise SystemExit(f'SQLite DB not found: {sqlite_path}')
    dsn = os.environ.get('COG_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not dsn:
        raise SystemExit('Missing COG_DATABASE_URL or DATABASE_URL')
    os.environ['COG_DB_ENGINE'] = 'postgres'
    os.environ['COG_DATABASE_URL'] = dsn

    import db  # local project module
    import psycopg
    from psycopg.rows import dict_row

    print(f'Initializing PostgreSQL schema in {dsn.split("@")[0]}@...')
    db.init_db()

    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row
    scur = sconn.cursor()

    pconn = psycopg.connect(dsn, row_factory=dict_row)
    pconn.autocommit = False
    pcur = pconn.cursor()

    scur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    sqlite_tables = [r['name'] for r in scur.fetchall()]
    ordered = [t for t in DEFAULT_ORDER if t in sqlite_tables] + [t for t in sqlite_tables if t not in DEFAULT_ORDER]

    # Clean destination but keep schema.
    print('Truncating destination tables...')
    try:
        tables_csv = ', '.join(f'"{t}"' for t in reversed(ordered) if t != 'schema_migrations')
        if tables_csv:
            pcur.execute(f'TRUNCATE {tables_csv} RESTART IDENTITY CASCADE')
            pconn.commit()
    except Exception as exc:
        pconn.rollback()
        print(f'Warning: could not truncate all tables at once: {exc}')

    pg_cols_cache: dict[str, list[str]] = {}
    sqlite_cols_cache: dict[str, list[str]] = {}

    def pg_cols(table: str) -> list[str]:
        if table not in pg_cols_cache:
            pcur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            pg_cols_cache[table] = [r['column_name'] for r in pcur.fetchall()]
        return pg_cols_cache[table]

    def sqlite_cols(table: str) -> list[str]:
        if table not in sqlite_cols_cache:
            scur.execute(f'PRAGMA table_info({table})')
            sqlite_cols_cache[table] = [r['name'] for r in scur.fetchall()]
        return sqlite_cols_cache[table]

    pending: dict[str, list[dict]] = defaultdict(list)
    total_inserted = 0

    for table in ordered:
        scur.execute(f'SELECT * FROM {table}')
        rows = [dict(r) for r in scur.fetchall()]
        if not rows:
            continue
        allowed = [c for c in sqlite_cols(table) if c in pg_cols(table)]
        if not allowed:
            print(f'Skipping {table}: no shared columns')
            continue
        pending[table] = [{c: row.get(c) for c in allowed} for row in rows]

    for pass_no in range(1, args.max_passes + 1):
        progress = 0
        print(f'Pass {pass_no}/{args.max_passes}...')
        for table in ordered:
            rows = pending.get(table) or []
            if not rows:
                continue
            cols = list(rows[0].keys())
            cols_sql = ', '.join(f'"{c}"' for c in cols)
            vals_sql = ', '.join(['%s'] * len(cols))
            sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({vals_sql}) ON CONFLICT DO NOTHING'
            still_pending = []
            for row in rows:
                try:
                    pcur.execute(sql, [row.get(c) for c in cols])
                    pconn.commit()
                    progress += 1
                except Exception:
                    pconn.rollback()
                    still_pending.append(row)
            pending[table] = still_pending
        total_inserted += progress
        if progress == 0:
            break

    remaining = {t: len(v) for t, v in pending.items() if v}
    if remaining:
        print('Rows still pending after retries:')
        for table, count in remaining.items():
            print(f'  - {table}: {count}')
    else:
        print('All rows migrated.')

    print('Resetting identity sequences...')
    for table in ordered:
        if 'id' in pg_cols(table):
            try:
                pcur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE((SELECT MAX(id) FROM \"" + table + "\"), 1), true)",
                    (table,),
                )
                pconn.commit()
            except Exception:
                pconn.rollback()

    pcur.close()
    pconn.close()
    sconn.close()
    print(f'Total inserted rows: {total_inserted}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

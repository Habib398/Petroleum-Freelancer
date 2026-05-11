from __future__ import annotations

import json
import datetime as _dt
from typing import Iterable

DEFAULT_REMINDER_DAYS = (60, 30, 15, 7, 3, 1, 0)

URL_MAP = {
    'normativas': '/petroleum/normativas',
    'expediente_normativas': '/petroleum/expedientes',
}

CALENDAR_KIND_MAP = {
    'normativas': 'normativa',
    'expediente_normativas': 'documento_normativa',
}

NOTIFICATION_TYPE_MAP = {
    'normativas': 'renewal',
    'expediente_normativas': 'renewal_document',
}



def parse_date(value: str | None) -> _dt.date | None:
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(raw[:10])
    except Exception:
        return None


def parse_reminder_days(raw: str | None, fallback: Iterable[int] = DEFAULT_REMINDER_DAYS) -> list[int]:
    vals: list[int] = []
    if raw:
        for part in str(raw).replace(';', ',').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                vals.append(max(0, int(part)))
            except Exception:
                continue
    if not vals:
        vals = [int(x) for x in fallback]
    return sorted(set(vals), reverse=True)


def urgency_meta(due_date: str | None, today: _dt.date | None = None) -> dict:
    d = parse_date(due_date)
    today = today or _dt.date.today()
    if not d:
        return {'urgency': 'sin_fecha', 'label': 'Sin fecha', 'color': '#64748b', 'days_left': None}
    delta = (d - today).days
    if delta < 0:
        return {'urgency': 'vencido', 'label': f'Vencido hace {abs(delta)} día(s)', 'color': '#dc2626', 'days_left': delta}
    if delta == 0:
        return {'urgency': 'hoy', 'label': 'Vence hoy', 'color': '#ea580c', 'days_left': delta}
    if delta <= 7:
        return {'urgency': 'critico', 'label': f'Vence en {delta} día(s)', 'color': '#f97316', 'days_left': delta}
    if delta <= 15:
        return {'urgency': 'atencion', 'label': f'Vence en {delta} día(s)', 'color': '#f59e0b', 'days_left': delta}
    if delta <= 30:
        return {'urgency': 'proximo', 'label': f'Vence en {delta} día(s)', 'color': '#eab308', 'days_left': delta}
    return {'urgency': 'programado', 'label': f'Vence en {delta} día(s)', 'color': '#2563eb', 'days_left': delta}



def calendar_kind_for_module(module: str | None) -> str:
    key = (module or '').strip().lower()
    return CALENDAR_KIND_MAP.get(key, key or 'documento')


def notification_type_for_module(module: str | None) -> str:
    key = (module or '').strip().lower()
    return NOTIFICATION_TYPE_MAP.get(key, 'renewal')


def route_for_module(module: str, is_admin: bool = True, brand: str | None = None) -> str:
    module = (module or '').strip().lower()
    brand = (brand or '').strip().lower()
    if not is_admin:
        if module in {'normativas', 'expediente_normativas'} and brand == 'petroleum':
            return '/petroleum/normativas' if module == 'normativas' else '/petroleum/expedientes'
    return URL_MAP.get(module, '/mod/document-renewals-calendar')


def scope_label(station_code: str | None, station_name: str | None, owner_name: str | None = None, client_name: str | None = None) -> str:
    if owner_name and owner_name.strip():
        return owner_name.strip()
    if client_name and client_name.strip():
        return client_name.strip()
    val = f"{station_code or ''} · {station_name or ''}".strip(' ·')
    return val or 'Sin asignar'


SOURCE_TABLES = ('tramites', 'normativas', 'expediente_records')


def sync_document_deadlines(conn, brand: str | None = None) -> int:
    brands = [brand] if brand else ['consulting', 'petroleum']
    cur = conn.cursor()
    total = 0
    for active_brand in brands:
        seen: dict[str, set[int]] = {tbl: set() for tbl in SOURCE_TABLES}
        rows: list[dict] = []
        if active_brand == 'petroleum':
            cur.execute(
                "SELECT n.id, n.station_id, n.norma_title AS title, n.folio, n.compliance_date AS issue_date, n.next_due_date AS due_date, "
                "COALESCE(n.renewable,1) AS renewable, COALESCE(n.periodicity,'mensual') AS periodicity, n.responsible_user_id, n.status, n.observations AS notes, n.evidence_path AS file_path, "
                "COALESCE(n.reminder_days,'60,30,15,7,3,1,0') AS reminder_days, s.code AS station_code, s.name AS station_name "
                "FROM normativas n LEFT JOIN stations s ON s.id=n.station_id WHERE n.brand='petroleum' AND n.next_due_date IS NOT NULL AND TRIM(COALESCE(n.next_due_date,''))<>'' AND COALESCE(n.status,'')<>'no_aplica'"
            )
            for r in cur.fetchall():
                row = dict(r)
                rows.append({
                    'brand': 'petroleum', 'source_table': 'normativas', 'source_id': int(row['id']), 'module': 'normativas',
                    'station_id': row.get('station_id'), 'owner_name': None, 'client_name': None,
                    'title': row.get('title') or 'Normativa', 'folio': row.get('folio') or '', 'issue_date': row.get('issue_date'), 'due_date': row.get('due_date'),
                    'renewable': int(row.get('renewable') or 1), 'periodicity': row.get('periodicity') or 'mensual',
                    'responsible_user_id': row.get('responsible_user_id'), 'status': row.get('status') or 'en_proceso', 'notes': row.get('notes') or '',
                    'file_path': row.get('file_path'), 'version_count': 1 if row.get('file_path') else 0,
                    'reminder_days': row.get('reminder_days') or '60,30,15,7,3,1,0',
                    'scope_label': scope_label(row.get('station_code'), row.get('station_name')),
                    'meta_json': json.dumps({'station_code': row.get('station_code'), 'station_name': row.get('station_name')}, ensure_ascii=False),
                })
                seen['normativas'].add(int(row['id']))

            cur.execute(
                "SELECT er.id, er.station_id, er.title, er.folio, er.issue_date, er.expiry_date AS due_date, COALESCE(er.renewable,1) AS renewable, COALESCE(er.periodicity,'anual') AS periodicity, "
                "COALESCE(er.responsible_user_id,NULL) AS responsible_user_id, er.status, er.notes, er.current_file_path AS file_path, COALESCE(er.version_count,0) AS version_count, COALESCE(er.reminder_days,'60,30,15,7,3,1,0') AS reminder_days, s.code AS station_code, s.name AS station_name "
                "FROM expediente_records er LEFT JOIN stations s ON s.id=er.station_id WHERE er.brand='petroleum' AND er.area='normativas' AND er.expiry_date IS NOT NULL AND TRIM(COALESCE(er.expiry_date,''))<>'' AND COALESCE(er.status,'')<>'no_aplica'"
            )
            for r in cur.fetchall():
                row = dict(r)
                rows.append({
                    'brand': 'petroleum', 'source_table': 'expediente_records', 'source_id': int(row['id']), 'module': 'expediente_normativas',
                    'station_id': row.get('station_id'), 'owner_name': None, 'client_name': None,
                    'title': row.get('title') or 'Documento normativo', 'folio': row.get('folio') or '', 'issue_date': row.get('issue_date'), 'due_date': row.get('due_date'),
                    'renewable': int(row.get('renewable') or 1), 'periodicity': row.get('periodicity') or 'anual',
                    'responsible_user_id': row.get('responsible_user_id'), 'status': row.get('status') or 'faltante', 'notes': row.get('notes') or '',
                    'file_path': row.get('file_path'), 'version_count': int(row.get('version_count') or 0),
                    'reminder_days': row.get('reminder_days') or '60,30,15,7,3,1,0',
                    'scope_label': scope_label(row.get('station_code'), row.get('station_name')),
                    'meta_json': json.dumps({'station_code': row.get('station_code'), 'station_name': row.get('station_name')}, ensure_ascii=False),
                })
                seen['expediente_records'].add(int(row['id']))

        for row in rows:
            cur.execute(
                "INSERT INTO document_deadlines (brand, source_table, source_id, module, station_id, owner_name, client_name, title, folio, issue_date, due_date, renewable, periodicity, responsible_user_id, status, notes, file_path, version_count, reminder_days, scope_label, meta_json, last_synced_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(brand, source_table, source_id) DO UPDATE SET module=excluded.module, station_id=excluded.station_id, owner_name=excluded.owner_name, client_name=excluded.client_name, title=excluded.title, folio=excluded.folio, issue_date=excluded.issue_date, due_date=excluded.due_date, renewable=excluded.renewable, periodicity=excluded.periodicity, responsible_user_id=excluded.responsible_user_id, status=excluded.status, notes=excluded.notes, file_path=excluded.file_path, version_count=excluded.version_count, reminder_days=excluded.reminder_days, scope_label=excluded.scope_label, meta_json=excluded.meta_json, last_synced_at=CURRENT_TIMESTAMP",
                (
                    row['brand'], row['source_table'], row['source_id'], row['module'], row['station_id'], row['owner_name'], row['client_name'],
                    row['title'], row['folio'], row['issue_date'], row['due_date'], row['renewable'], row['periodicity'], row['responsible_user_id'],
                    row['status'], row['notes'], row['file_path'], row['version_count'], row['reminder_days'], row['scope_label'], row['meta_json'],
                ),
            )
            total += 1

        for source_table, ids in seen.items():
            if ids:
                placeholders = ','.join(['?'] * len(ids))
                cur.execute(
                    f"DELETE FROM document_deadlines WHERE brand=? AND source_table=? AND source_id NOT IN ({placeholders})",
                    (active_brand, source_table, *sorted(ids)),
                )
            else:
                cur.execute("DELETE FROM document_deadlines WHERE brand=? AND source_table=?", (active_brand, source_table))
    return total


def list_document_deadlines(conn, brand: str, *, date_from: str | None = None, date_to: str | None = None, station_ids: Iterable[int] | None = None, module: str | None = None, urgency: str | None = None, q: str | None = None) -> list[dict]:
    cur = conn.cursor()
    sql = "SELECT dd.*, s.code AS station_code, s.name AS station_name, u.username AS responsible_name FROM document_deadlines dd LEFT JOIN stations s ON s.id=dd.station_id LEFT JOIN users u ON u.id=dd.responsible_user_id WHERE dd.brand=?"
    params: list = [brand]
    if date_from:
        sql += ' AND dd.due_date>=?'
        params.append(date_from)
    if date_to:
        sql += ' AND dd.due_date<=?'
        params.append(date_to)
    if module:
        sql += ' AND dd.module=?'
        params.append(module)
    if station_ids:
        ids = [int(x) for x in station_ids if int(x)]
        if ids:
            sql += ' AND dd.station_id IN (%s)' % ','.join(['?'] * len(ids))
            params.extend(ids)
    if q:
        sql += " AND LOWER(COALESCE(dd.title,'') || ' ' || COALESCE(dd.folio,'') || ' ' || COALESCE(dd.scope_label,'') || ' ' || COALESCE(dd.notes,'')) LIKE ?"
        params.append(f"%{str(q).strip().lower()}%")
    sql += ' ORDER BY COALESCE(dd.due_date,\'9999-12-31\') ASC, dd.title ASC'
    cur.execute(sql, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    out = []
    for row in rows:
        meta = urgency_meta(row.get('due_date'))
        if urgency and meta['urgency'] != urgency:
            continue
        row.update(meta)
        row['file_url'] = '/uploads/' + row['file_path'] if row.get('file_path') else None
        row['url'] = route_for_module(row.get('module'), is_admin=True, brand=brand)
        row['scope_label'] = row.get('scope_label') or scope_label(row.get('station_code'), row.get('station_name'), owner_name=row.get('owner_name'), client_name=row.get('client_name'))
        out.append(row)
    return out


def deadlines_summary(rows: list[dict]) -> dict:
    out = {'total': len(rows), 'vigentes': 0, 'proximos': 0, 'criticos': 0, 'vencidos': 0, 'sin_fecha': 0}
    for row in rows:
        urg = row.get('urgency')
        if urg == 'vencido':
            out['vencidos'] += 1
        elif urg in {'hoy', 'critico'}:
            out['criticos'] += 1
        elif urg in {'atencion', 'proximo'}:
            out['proximos'] += 1
        elif urg == 'sin_fecha':
            out['sin_fecha'] += 1
        else:
            out['vigentes'] += 1
    return out


def notification_notice_kind(days_left: int | None) -> str | None:
    if days_left is None:
        return None
    if days_left < 0:
        return 'overdue'
    if days_left in {30, 15, 7, 3, 1, 0}:
        return f'due_{days_left}d'
    return None


def log_deadline_notification(conn, deadline_id: int, user_id: int, notice_key: str, channel: str = 'in_app') -> bool:
    try:
        conn.execute(
            'INSERT INTO deadline_notifications_log (deadline_id, user_id, notice_key, channel) VALUES (?,?,?,?)',
            (int(deadline_id), int(user_id), str(notice_key), channel),
        )
        return True
    except Exception:
        return False


def renew_deadline_source(conn, deadline_id: int, *, new_due_date: str, renewed_by: int | None, notes: str = '') -> dict | None:
    cur = conn.cursor()
    cur.execute('SELECT * FROM document_deadlines WHERE id=?', (int(deadline_id),))
    row = cur.fetchone()
    if not row:
        return None
    row = dict(row)
    today = _dt.date.today().isoformat()
    source_table = row['source_table']
    source_id = int(row['source_id'])
    old_due = row.get('due_date')
    old_status = row.get('status')
    old_file = row.get('file_path')
    if source_table == 'tramites':
        conn.execute(
            "UPDATE tramites SET due_date=?, last_renewal_date=?, status=CASE WHEN status='vencido' THEN 'en_proceso' ELSE status END, updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=? AND brand=?",
            (new_due_date, today, int(renewed_by) if renewed_by else None, source_id, row['brand']),
        )
    elif source_table == 'normativas':
        conn.execute(
            "UPDATE normativas SET compliance_date=?, next_due_date=?, last_renewal_date=?, status='cumple', updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=? AND brand=?",
            (today, new_due_date, today, int(renewed_by) if renewed_by else None, source_id, row['brand']),
        )
    elif source_table == 'expediente_records':
        conn.execute(
            "UPDATE expediente_records SET expiry_date=?, last_renewal_date=?, status='vigente', updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=? AND brand=?",
            (new_due_date, today, int(renewed_by) if renewed_by else None, source_id, row['brand']),
        )
    else:
        return None
    conn.execute(
        'INSERT INTO document_renewal_history (brand, deadline_id, source_table, source_id, old_due_date, new_due_date, old_status, new_status, old_file_path, new_file_path, notes, renewed_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (row['brand'], int(deadline_id), source_table, source_id, old_due, new_due_date, old_status, 'vigente' if source_table == 'expediente_records' else ('cumple' if source_table == 'normativas' else 'en_proceso'), old_file, row.get('file_path'), notes, int(renewed_by) if renewed_by else None),
    )
    sync_document_deadlines(conn, row['brand'])
    cur.execute('SELECT * FROM document_deadlines WHERE brand=? AND source_table=? AND source_id=?', (row['brand'], source_table, source_id))
    new_row = cur.fetchone()
    return dict(new_row) if new_row else row

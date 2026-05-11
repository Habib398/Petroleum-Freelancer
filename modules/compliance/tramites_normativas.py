from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from flask import jsonify, render_template, request, send_file, redirect

from db import get_conn
from services.brand import get_brand
from services.deadlines import calendar_kind_for_module, deadlines_summary, list_document_deadlines, renew_deadline_source, route_for_module, sync_document_deadlines, urgency_meta, parse_date as deadline_parse_date
from services.branding import NORMATIVE_DEFAULTS, get_normative_config


TRAMITE_STATUSES = [
    "pendiente",
    "en_proceso",
    "en_revision",
    "requiere_correccion",
    "finalizado",
    "vencido",
    "cancelado",
]
TRAMITE_PRIORITIES = ["baja", "media", "alta", "critica"]
TRAMITE_DEPENDENCIES = [
    "ASEA",
    "CRE",
    "Proteccion Civil",
    "Municipio",
    "Estado",
    "Interno",
    "Otra",
]
TRAMITE_TYPES = [
    "Permiso",
    "Renovacion",
    "Oficio",
    "Licencia",
    "Gestion ambiental",
    "Gestion operativa",
    "Entrega documental",
    "Respuesta a observacion",
]

NORMATIVA_STATUSES = [
    "cumple",
    "proximo_a_vencer",
    "vencido",
    "en_proceso",
    "no_aplica",
    "en_revision",
]
NORMATIVA_PERIODICITIES = ["mensual", "bimestral", "trimestral", "semestral", "anual", "eventual"]
NORMATIVA_RISKS = ["bajo", "medio", "alto", "critico"]
NORMATIVA_CATEGORIES = [
    "Seguridad",
    "Operacion",
    "Ambiental",
    "Mantenimiento",
    "Capacitacion",
    "Inspeccion",
    "Documentacion legal",
    "Verificaciones",
]



EXPEDIENTE_STATUSES = ['faltante', 'vigente', 'proximo_a_vencer', 'vencido', 'en_revision', 'no_aplica']
EXPEDIENTE_AREAS = {'tramites': 'consulting', 'normativas': 'petroleum'}
EXPEDIENTE_LABELS = {'tramites': 'Trámites', 'normativas': 'Normativas'}


def _petroleum_norm_cfg():
    return get_normative_config('petroleum')


def _apply_petroleum_catalog_branding(items):
    cfg_map = _petroleum_norm_cfg()
    rows = []
    for item in items or []:
        d = dict(item)
        code = (d.get('code') or '').strip().lower()
        cfg = cfg_map.get(code)
        if code in NORMATIVE_DEFAULTS:
            if not cfg or not cfg.get('enabled', True):
                continue
            d['title'] = cfg.get('title') or d.get('title')
            d['sort_order'] = int(cfg.get('order') or d.get('sort_order') or 0)
            d['accent_color'] = cfg.get('color')
            d['icon'] = cfg.get('icon') or d.get('icon') or '•'
            d['description'] = cfg.get('description') or d.get('description') or ''
        rows.append(d)
    rows.sort(key=lambda item: (int(item.get('sort_order') or 0), item.get('id') or 0))
    return rows


def _apply_petroleum_normativa_branding(items):
    cfg_map = _petroleum_norm_cfg()
    rows = []
    for item in items or []:
        d = dict(item)
        code = (d.get('catalog_code') or '').strip().lower()
        cfg = cfg_map.get(code)
        if code in NORMATIVE_DEFAULTS:
            if not cfg or not cfg.get('enabled', True):
                continue
            d['norma_title'] = cfg.get('title') or d.get('norma_title')
            d['catalog_title'] = cfg.get('title') or d.get('catalog_title')
            d['accent_color'] = cfg.get('color')
            d['sort_order'] = int(cfg.get('order') or d.get('sort_order') or 0)
            d['icon'] = cfg.get('icon') or d.get('icon') or '•'
            d['description'] = cfg.get('description') or d.get('description') or ''
        rows.append(d)
    rows.sort(key=lambda item: (
        0 if (item.get('status') == 'vencido') else 1 if (item.get('status') == 'proximo_a_vencer') else 2 if (item.get('status') == 'en_proceso') else 3,
        str(item.get('next_due_date') or '9999-12-31'),
        -int(item.get('id') or 0),
    ))
    return rows


def _exp_effective_status(status: str | None, expiry_date: str | None) -> str:
    status = (status or 'faltante').strip().lower()
    if status == 'no_aplica':
        return status
    if expiry_date:
        try:
            exp = date.fromisoformat(expiry_date[:10])
            today = date.today()
            if exp < today:
                return 'vencido'
            if exp <= today + timedelta(days=30) and status in {'vigente', 'faltante', 'proximo_a_vencer'}:
                return 'proximo_a_vencer'
        except Exception:
            pass
    return status or 'faltante'


def _exp_scope_where(area: str, station_id, owner_name: str | None):
    owner = (owner_name or '').strip().lower()
    if area == 'tramites':
        if station_id:
            return 'er.station_id=?', [int(station_id)]
        if owner:
            return 'er.station_id IS NULL AND LOWER(COALESCE(er.owner_name,''))=?', [owner]
        return '1=0', []
    return 'er.station_id=?', [int(station_id or 0)] if station_id else []


def _exp_template_where(area: str, brand: str):
    return "SELECT id, code, title, description, is_required, default_validity_days, sort_order, is_active FROM expediente_templates WHERE brand=? AND area=? AND is_active=1 ORDER BY sort_order ASC, id ASC", (brand, area)


def _exp_scope_label(station_row: dict | None, owner_name: str | None):
    if station_row:
        return f"{station_row.get('code') or ''} · {station_row.get('name') or ''}".strip(' ·')
    return (owner_name or '').strip()


def _exp_summary_from_items(items: list[dict]):
    summary = {'total': len(items), 'faltante': 0, 'vigente': 0, 'proximo_a_vencer': 0, 'vencido': 0, 'en_revision': 0, 'no_aplica': 0, 'required_missing': 0}
    for item in items:
        st = _exp_effective_status(item.get('status'), item.get('expiry_date'))
        summary[st] = int(summary.get(st, 0)) + 1
        if item.get('is_required') and st == 'faltante':
            summary['required_missing'] += 1
    return summary


def _exp_brand_and_scope(ctx, area: str, me: dict, station_id, owner_name: str | None):
    brand = EXPEDIENTE_AREAS.get(area)
    if not brand:
        return None, None, ({'ok': False, 'error': 'invalid_area'}, 400)
    conn = get_conn(); cur = conn.cursor()
    station = None
    if station_id:
        cur.execute('SELECT id, brand, code, name FROM stations WHERE id=?', (int(station_id),))
        station = cur.fetchone()
        if not station or station['brand'] != brand:
            conn.close()
            return None, None, ({'ok': False, 'error': 'station_not_found'}, 404)
        if me.get('role') != 'admin' and not ctx.can_access_station(me, int(station_id)):
            conn.close()
            return None, None, ({'ok': False, 'error': 'forbidden_station'}, 403)
    conn.close()
    if area == 'normativas' and not station_id:
        return None, None, ({'ok': False, 'error': 'station_required'}, 400)
    if area == 'tramites' and not station_id and not (owner_name or '').strip():
        return None, None, ({'ok': False, 'error': 'scope_required'}, 400)
    return brand, dict(station) if station else None, None


def _exp_items_for_scope(area: str, brand: str, station_id, owner_name: str | None):
    conn = get_conn(); cur = conn.cursor()
    sql_tpl, params_tpl = _exp_template_where(area, brand)
    cur.execute(sql_tpl, params_tpl)
    templates = [dict(r) for r in cur.fetchall()]
    where, params = _exp_scope_where(area, station_id, owner_name)
    cur.execute(
        f"SELECT er.*, et.code AS template_code, et.title AS template_title, et.description AS template_description, COALESCE(et.is_required,0) AS is_required, et.default_validity_days FROM expediente_records er LEFT JOIN expediente_templates et ON et.id=er.template_id WHERE er.brand=? AND er.area=? AND {where} ORDER BY COALESCE(et.sort_order,9999) ASC, er.id DESC",
        (brand, area, *params),
    )
    record_rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    record_by_tpl = {}
    custom_rows = []
    for row in record_rows:
        if row.get('template_id'):
            record_by_tpl.setdefault(int(row['template_id']), row)
        else:
            row['computed_status'] = _exp_effective_status(row.get('status'), row.get('expiry_date'))
            custom_rows.append(row)
    items = []
    for tpl in templates:
        rec = record_by_tpl.get(int(tpl['id']))
        if rec:
            rec = dict(rec)
            rec['computed_status'] = _exp_effective_status(rec.get('status'), rec.get('expiry_date'))
            rec['missing'] = 0
            items.append(rec)
        else:
            items.append({
                'id': None,
                'template_id': tpl['id'],
                'template_code': tpl.get('code'),
                'title': tpl.get('title'),
                'template_title': tpl.get('title'),
                'template_description': tpl.get('description'),
                'status': 'faltante',
                'computed_status': 'faltante',
                'issue_date': None,
                'expiry_date': None,
                'notes': '',
                'current_file_path': None,
                'version_count': 0,
                'is_required': int(tpl.get('is_required') or 0),
                'missing': 1,
                'default_validity_days': tpl.get('default_validity_days'),
            })
    for row in custom_rows:
        row['missing'] = 0
        row['template_title'] = row.get('title')
        items.append(row)
    return items


def _today() -> str:
    return date.today().isoformat()


def _add_months_iso(start: str, months: int) -> str:
    try:
        y, m, d = [int(x) for x in (start or _today()).split('-')[:3]]
        m2 = m - 1 + months
        y += m2 // 12
        m = m2 % 12 + 1
        if m == 2:
            md = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
        elif m in {4, 6, 9, 11}:
            md = 30
        else:
            md = 31
        d = min(d, md)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return start or _today()


def _next_due_from(periodicity: str, from_date: str | None) -> str:
    base = from_date or _today()
    per = (periodicity or '').strip().lower()
    if per == 'mensual':
        return _add_months_iso(base, 1)
    if per == 'bimestral':
        return _add_months_iso(base, 2)
    if per == 'trimestral':
        return _add_months_iso(base, 3)
    if per == 'semestral':
        return _add_months_iso(base, 6)
    if per == 'anual':
        return _add_months_iso(base, 12)
    try:
        return (date.fromisoformat(base) + timedelta(days=30)).isoformat()
    except Exception:
        return base


def _station_scope_ids(ctx, me: dict) -> set[int]:
    if not me:
        return set()
    if me.get('role') == 'admin':
        return set()
    return ctx.station_scope_ids(me)


def _stations_for_brand(brand: str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, code, name, monthly_status FROM stations WHERE brand=? ORDER BY code ASC, name ASC", (brand,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _users_for_brand(brand: str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, station_id FROM users WHERE is_active=1 AND (allowed_brands LIKE ? OR primary_brand=? OR brand=?) ORDER BY username ASC",
        (f"%{brand}%", brand, brand),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _csv_response(filename: str, headers: list[str], rows: list[list[str]]):
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    bio = io.BytesIO(sio.getvalue().encode('utf-8-sig'))
    bio.seek(0)
    return send_file(bio, mimetype='text/csv; charset=utf-8', as_attachment=True, download_name=filename)


def _tramites_disabled_json(code: int = 410):
    return jsonify({
        'ok': False,
        'error': 'tramites_disabled',
        'message': 'Trámites de Consulting no está habilitado por ahora.'
    }), code


def _tramites_progress_payload(station_id: int):
    items = _exp_items_for_scope('tramites', 'consulting', station_id, None)
    summary = _exp_summary_from_items(items)
    scored_items = [i for i in items if int(i.get('is_required') or 0) == 1]
    if not scored_items:
        scored_items = list(items)
    weights = {
        'vigente': 1.0,
        'no_aplica': 1.0,
        'proximo_a_vencer': 0.85,
        'en_revision': 0.6,
        'vencido': 0.0,
        'faltante': 0.0,
    }
    total = len(scored_items)
    score = 0.0
    missing_items = []
    for item in items:
        st = _exp_effective_status(item.get('status'), item.get('expiry_date'))
        item['computed_status'] = st
        if item in scored_items:
            score += float(weights.get(st, 0.0))
        if st == 'faltante' and int(item.get('is_required') or 0) == 1:
            missing_items.append({
                'title': item.get('title') or item.get('template_title') or 'Documento',
                'template_code': item.get('template_code'),
                'template_id': item.get('template_id'),
            })
        item['file_url'] = ('/uploads/' + item['current_file_path']) if item.get('current_file_path') else None
    completion_pct = int(round((score / total) * 100)) if total else 0
    return {
        'items': items,
        'summary': summary,
        'completion_pct': completion_pct,
        'missing_required_items': missing_items,
        'complete': 1 if summary.get('required_missing', 0) == 0 and completion_pct >= 95 else 0,
    }


def _tramites_admin_grid_rows():
    stations = _stations_for_brand('consulting')
    rows = []
    station_cards = []
    totals = {'stations': len(stations), 'documents': 0, 'with_file': 0, 'required_missing': 0}
    for station in stations:
        payload = _tramites_progress_payload(int(station['id']))
        summary = payload['summary']
        station_cards.append({
            'station_id': station['id'],
            'station_code': station.get('code'),
            'station_name': station.get('name'),
            'completion_pct': payload['completion_pct'],
            'required_missing': summary.get('required_missing', 0),
            'total': summary.get('total', 0),
        })
        totals['required_missing'] += int(summary.get('required_missing') or 0)
        for item in payload['items']:
            totals['documents'] += 1
            if item.get('current_file_path'):
                totals['with_file'] += 1
            rows.append({
                'station_id': station['id'],
                'station_code': station.get('code'),
                'station_name': station.get('name'),
                'completion_pct': payload['completion_pct'],
                'document_id': item.get('id'),
                'folio': item.get('folio') or item.get('template_code') or '',
                'document_title': item.get('title') or item.get('template_title') or '',
                'status': item.get('computed_status') or item.get('status') or 'faltante',
                'issue_date': item.get('issue_date') or '',
                'expiry_date': item.get('expiry_date') or '',
                'notes': item.get('notes') or '',
                'is_required': int(item.get('is_required') or 0),
                'version_count': int(item.get('version_count') or 0),
                'current_file_path': item.get('current_file_path'),
                'file_url': ('/uploads/' + item['current_file_path']) if item.get('current_file_path') else None,
            })
    return rows, station_cards, totals

def _iso_date_or_none(value: str | None):
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def _calendar_urgency_parts(target_date):
    d = _iso_date_or_none(target_date) if isinstance(target_date, str) else target_date
    if not d:
        return {'urgency': 'sin_fecha', 'label': 'Sin fecha', 'color': '#64748b', 'days_left': None}
    today = date.today()
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


def _document_calendar_items(ctx, me: dict, brand: str, d_from: date, d_to: date):
    conn = get_conn()
    try:
        sync_document_deadlines(conn, brand)
        scope = _station_scope_ids(ctx, me)
        rows = list_document_deadlines(
            conn,
            brand,
            date_from=d_from.isoformat(),
            date_to=d_to.isoformat(),
            station_ids=sorted(scope) if scope else None,
        )
    finally:
        conn.close()
    is_admin = (me.get('role') == 'admin')
    items = []
    for row in rows:
        row = dict(row)
        row['kind'] = calendar_kind_for_module(row.get('module'))
        row['date'] = row.get('due_date')
        row['url'] = route_for_module(row.get('module'), is_admin=is_admin, brand=brand)
        items.append(row)
    items.sort(key=lambda it: (it.get('date') or '9999-12-31', it.get('title') or ''))
    return items



def register(app):
    ctx = app.extensions['ctx']
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get('/admin/tramites')
    @login_required
    @role_required('admin')
    def tramites_page():
        return redirect('/admin/document-center')

    @app.get('/staff/tramites')
    @login_required
    def staff_tramites_page():
        return redirect('/mod/dashboard')

    @app.get('/admin/tramites/control-documental')
    @login_required
    @role_required('admin')
    def admin_tramites_control_documental_page():
        return redirect('/admin/document-center')

    @app.get('/admin/document-deadlines')
    @login_required
    @role_required('admin')
    def admin_document_deadlines_page():
        return render_template('admin/document_deadlines.html', active_brand=get_brand())

    @app.get('/mod/document-renewals-calendar')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def document_renewals_calendar_page():
        return render_template('mod/document_renewals_calendar.html', active_brand=get_brand())

    @app.get('/api/document-renewals-calendar')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def api_document_renewals_calendar():
        me = ctx.get_me() or {}
        brand = get_brand()
        raw_from = (request.args.get('from') or '').strip()
        raw_to = (request.args.get('to') or '').strip()
        module = (request.args.get('module') or '').strip().lower() or None
        urgency = (request.args.get('urgency') or '').strip().lower() or None
        q = (request.args.get('q') or '').strip()
        station_id = int(request.args.get('station_id') or 0) or None
        today_local = date.today()
        d_from = _iso_date_or_none(raw_from) or today_local.replace(day=1)
        d_to = _iso_date_or_none(raw_to) or (d_from + timedelta(days=62))
        if d_to < d_from:
            d_from, d_to = d_to, d_from
        conn = get_conn()
        try:
            sync_document_deadlines(conn, brand)
            scope = _station_scope_ids(ctx, me)
            station_ids = sorted(scope) if scope else None
            if station_id:
                if scope and station_id not in scope:
                    return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
                station_ids = [station_id]
            items = list_document_deadlines(conn, brand, date_from=d_from.isoformat(), date_to=d_to.isoformat(), station_ids=station_ids, module=module, urgency=urgency, q=q)
        finally:
            conn.close()
        is_admin = (me.get('role') == 'admin')
        for item in items:
            item['kind'] = calendar_kind_for_module(item.get('module'))
            item['date'] = item.get('due_date')
            item['url'] = route_for_module(item.get('module'), is_admin=is_admin, brand=brand)
        return jsonify({'ok': True, 'brand': brand, 'from': d_from.isoformat(), 'to': d_to.isoformat(), 'items': items, 'summary': deadlines_summary(items), 'stations': _stations_for_brand(brand)})

    @app.get('/api/document-deadlines')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def api_document_deadlines_grid():
        me = ctx.get_me() or {}
        brand = get_brand()
        module = (request.args.get('module') or '').strip().lower() or None
        urgency = (request.args.get('urgency') or '').strip().lower() or None
        q = (request.args.get('q') or '').strip()
        station_id = int(request.args.get('station_id') or 0) or None
        raw_from = (request.args.get('from') or '').strip() or None
        raw_to = (request.args.get('to') or '').strip() or None
        conn = get_conn()
        try:
            sync_document_deadlines(conn, brand)
            scope = _station_scope_ids(ctx, me)
            station_ids = sorted(scope) if scope else None
            if station_id:
                if scope and station_id not in scope:
                    return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
                station_ids = [station_id]
            rows = list_document_deadlines(conn, brand, date_from=raw_from, date_to=raw_to, station_ids=station_ids, module=module, urgency=urgency, q=q)
        finally:
            conn.close()
        is_admin = (me.get('role') == 'admin')
        for item in rows:
            item['kind'] = calendar_kind_for_module(item.get('module'))
            item['url'] = route_for_module(item.get('module'), is_admin=is_admin, brand=brand)
        return jsonify({'ok': True, 'rows': rows, 'summary': deadlines_summary(rows), 'stations': _stations_for_brand(brand), 'brand': brand})

    @app.get('/api/document-deadlines/export.csv')
    @login_required
    @role_required('admin')
    def api_document_deadlines_export_csv():
        brand = get_brand()
        conn = get_conn()
        try:
            sync_document_deadlines(conn, brand)
            rows = list_document_deadlines(conn, brand)
        finally:
            conn.close()
        csv_rows = []
        for r in rows:
            csv_rows.append([
                r.get('module') or '', r.get('scope_label') or '', r.get('station_code') or '', r.get('station_name') or '', r.get('title') or '', r.get('folio') or '',
                r.get('status') or '', r.get('urgency') or '', r.get('due_date') or '', r.get('days_left') if r.get('days_left') is not None else '', r.get('responsible_name') or '', r.get('file_path') or '', r.get('notes') or ''
            ])
        return _csv_response('control_maestro_vencimientos.csv', ['Modulo','Scope','Codigo estacion','Estacion','Documento','Folio','Estatus','Urgencia','Vence','Dias restantes','Responsable','Archivo','Notas'], csv_rows)

    @app.get('/api/document-deadlines/<int:deadline_id>/history')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def api_document_deadline_history(deadline_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        conn = get_conn(); cur = conn.cursor()
        cur.execute('SELECT station_id FROM document_deadlines WHERE id=? AND brand=?', (deadline_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        station_id = int(row['station_id'] or 0) or None
        if me.get('role') != 'admin' and station_id and not ctx.can_access_station(me, station_id):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        cur.execute('SELECT h.*, u.username AS renewed_by_name FROM document_renewal_history h LEFT JOIN users u ON u.id=h.renewed_by WHERE h.deadline_id=? ORDER BY h.id DESC', (deadline_id,))
        items = _apply_petroleum_normativa_branding([dict(r) for r in cur.fetchall()])
        conn.close()
        return jsonify({'ok': True, 'items': items})

    @app.post('/api/document-deadlines/<int:deadline_id>/renew')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def api_document_deadline_renew(deadline_id: int):
        me = ctx.get_me() or {}
        brand = get_brand()
        data = request.get_json(silent=True) or {}
        new_due_date = (data.get('new_due_date') or '').strip()
        if not deadline_parse_date(new_due_date):
            return jsonify({'ok': False, 'error': 'invalid_due_date'}), 400
        notes = (data.get('notes') or '').strip()
        conn = get_conn(); cur = conn.cursor()
        cur.execute('SELECT * FROM document_deadlines WHERE id=? AND brand=?', (deadline_id, brand))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        row = dict(row)
        station_id = int(row.get('station_id') or 0) or None
        if me.get('role') != 'admin' and ((station_id and not ctx.can_access_station(me, station_id)) or (not station_id and row.get('owner_name'))):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        updated = renew_deadline_source(conn, deadline_id, new_due_date=new_due_date, renewed_by=int(me.get('id') or 0) or None, notes=notes)
        conn.commit()
        conn.close()
        if not updated:
            return jsonify({'ok': False, 'error': 'renewal_failed'}), 400
        ctx.log_action(me, 'renew_document_deadline', row.get('source_table') or 'document_deadlines', str(row.get('source_id')), {'deadline_id': deadline_id, 'new_due_date': new_due_date})
        return jsonify({'ok': True, 'item': updated})

    @app.get('/api/tramites/my-expediente')
    @login_required
    @role_required('jefe_estacion','operador')
    def api_tramites_my_expediente():
        return _tramites_disabled_json()

    @app.post('/api/tramites/my-expediente/records')
    @login_required
    @role_required('jefe_estacion','operador')
    def api_tramites_my_expediente_upsert():
        return _tramites_disabled_json()

    @app.post('/api/tramites/my-expediente/<int:record_id>/file')
    @login_required
    @role_required('jefe_estacion','operador')
    def api_tramites_my_expediente_file(record_id: int):
        return _tramites_disabled_json()

    @app.get('/api/tramites/control-documental')
    @login_required
    @role_required('admin')
    def api_tramites_control_documental():
        return _tramites_disabled_json()

    @app.get('/api/tramites/control-documental/export.csv')
    @login_required
    @role_required('admin')
    def api_tramites_control_documental_export():
        return _tramites_disabled_json()

    @app.get('/api/tramites/meta')
    @login_required
    @role_required('admin')
    def api_tramites_meta():
        return _tramites_disabled_json()

    @app.get('/api/tramites')
    @login_required
    @role_required('admin')
    def api_tramites_list():
        return _tramites_disabled_json()

    @app.post('/api/tramites')
    @login_required
    @role_required('admin')
    def api_tramites_create():
        return _tramites_disabled_json()

    @app.patch('/api/tramites/<int:tramite_id>')
    @login_required
    @role_required('admin')
    def api_tramites_update(tramite_id: int):
        return _tramites_disabled_json()

    @app.post('/api/tramites/<int:tramite_id>/attachment')
    @login_required
    @role_required('admin')
    def api_tramites_attachment(tramite_id: int):
        return _tramites_disabled_json()

    @app.get('/api/tramites/export.csv')
    @login_required
    @role_required('admin')
    def api_tramites_export_csv():
        return _tramites_disabled_json()

    @app.get('/petroleum/normativas-control')
    @login_required
    @role_required('admin')
    def normativas_page():
        return render_template('petroleum/control_vigencias.html')

    @app.get('/api/normativas/meta')
    @login_required
    @role_required('admin')
    def api_normativas_meta():
        brand = 'petroleum'
        me = ctx.get_me() or {}
        stations = _stations_for_brand(brand)
        scope = _station_scope_ids(ctx, me)
        if scope:
            stations = [s for s in stations if int(s['id']) in scope]
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, title, category, description, periodicity, default_risk, sort_order, is_active FROM normative_catalog WHERE brand='petroleum' ORDER BY sort_order ASC, id ASC")
        catalog = _apply_petroleum_catalog_branding([dict(r) for r in cur.fetchall()])
        conn.close()
        return jsonify({
            'ok': True,
            'stations': stations,
            'users': _users_for_brand(brand),
            'statuses': NORMATIVA_STATUSES,
            'periodicities': NORMATIVA_PERIODICITIES,
            'risks': NORMATIVA_RISKS,
            'categories': NORMATIVA_CATEGORIES,
            'catalog': catalog,
            'can_manage_catalog': me.get('role') == 'admin',
        })

    @app.get('/api/normativas')
    @login_required
    @role_required('admin')
    def api_normativas_list():
        me = ctx.get_me() or {}
        q = (request.args.get('q') or '').strip().lower()
        status = (request.args.get('status') or '').strip().lower()
        station_id = (request.args.get('station_id') or '').strip()
        conn = get_conn(); cur = conn.cursor()
        sql = (
            "SELECT n.*, s.code AS station_code, s.name AS station_name, u.username AS responsible_name, c.code AS catalog_code "
            "FROM normativas n "
            "LEFT JOIN stations s ON s.id=n.station_id "
            "LEFT JOIN users u ON u.id=n.responsible_user_id "
            "LEFT JOIN normative_catalog c ON c.id=n.catalog_id "
            "WHERE n.brand='petroleum'"
        )
        params = []
        scope = _station_scope_ids(ctx, me)
        if scope:
            sql += ' AND n.station_id IN (%s)' % (','.join(['?'] * len(scope)))
            params.extend(sorted(scope))
        if status:
            sql += ' AND n.status=?'
            params.append(status)
        if station_id:
            sql += ' AND n.station_id=?'
            params.append(int(station_id))
        if q:
            sql += " AND LOWER(COALESCE(n.folio,'') || ' ' || COALESCE(n.norma_title,'') || ' ' || COALESCE(n.category,'') || ' ' || COALESCE(n.description,'') || ' ' || COALESCE(n.observations,'')) LIKE ?"
            params.append(f'%{q}%')
        sql += " ORDER BY CASE n.status WHEN 'vencido' THEN 0 WHEN 'proximo_a_vencer' THEN 1 WHEN 'en_proceso' THEN 2 ELSE 3 END, COALESCE(n.next_due_date,'9999-12-31') ASC, n.id DESC"
        cur.execute(sql, tuple(params))
        items = _apply_petroleum_normativa_branding([dict(r) for r in cur.fetchall()])
        conn.close()
        return jsonify({'ok': True, 'items': items})

    @app.post('/api/normativas')
    @login_required
    @role_required('admin')
    def api_normativas_create():
        me = ctx.get_me() or {}
        data = request.get_json(silent=True) or {}
        station_id = int(data.get('station_id') or 0) or None
        if not station_id:
            return jsonify({'ok': False, 'error': 'station_required'}), 400
        if me.get('role') != 'admin' and not ctx.can_access_station(me, station_id):
            return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        responsible_user_id = int(data.get('responsible_user_id') or 0) or None
        catalog_id = int(data.get('catalog_id') or 0) or None
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM stations WHERE id=? AND brand='petroleum'", (station_id,))
        st = cur.fetchone()
        if not st:
            conn.close(); return jsonify({'ok': False, 'error': 'station_not_found'}), 404
        cat = None
        if catalog_id:
            cur.execute("SELECT * FROM normative_catalog WHERE id=? AND brand='petroleum'", (catalog_id,))
            cat = cur.fetchone()
            if cat:
                cat = dict(cat)
                code = (cat.get('code') or '').strip().lower()
                cfg = _petroleum_norm_cfg().get(code)
                if code in NORMATIVE_DEFAULTS and cfg and cfg.get('enabled', True):
                    cat['title'] = cfg.get('title') or cat.get('title')
                    cat['sort_order'] = cfg.get('order') or cat.get('sort_order')
                elif code in NORMATIVE_DEFAULTS and cfg and not cfg.get('enabled', True):
                    cat = None
            if not cat:
                conn.close(); return jsonify({'ok': False, 'error': 'catalog_not_found'}), 404
        norma_title = (data.get('norma_title') or (cat.get('title') if cat else '') or '').strip()
        category = (data.get('category') or (cat.get('category') if cat else '') or '').strip() or 'Seguridad'
        description = (data.get('description') or (cat.get('description') if cat else '') or '').strip()
        periodicity = (data.get('periodicity') or (cat.get('periodicity') if cat else '') or 'mensual').strip().lower()
        risk_level = (data.get('risk_level') or (cat.get('default_risk') if cat else '') or 'medio').strip().lower()
        compliance_date = (data.get('compliance_date') or _today()).strip()
        next_due_date = (data.get('next_due_date') or '').strip() or _next_due_from(periodicity, compliance_date)
        status = (data.get('status') or 'en_proceso').strip().lower()
        observations = (data.get('observations') or '').strip()
        renewable = 0 if str(data.get('renewable', '1')).lower() in {'0','false','no'} else 1
        reminder_days = (data.get('reminder_days') or '60,30,15,7,3,1,0').strip()
        if status not in NORMATIVA_STATUSES:
            status = 'en_proceso'
        if periodicity not in NORMATIVA_PERIODICITIES:
            periodicity = 'eventual'
        if risk_level not in NORMATIVA_RISKS:
            risk_level = 'medio'
        cur.execute(
            "INSERT INTO normativas (brand, station_id, catalog_id, norma_title, category, description, periodicity, compliance_date, next_due_date, responsible_user_id, status, observations, risk_level, renewable, reminder_days, created_by, updated_by) VALUES ('petroleum',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (station_id, catalog_id, norma_title, category, description, periodicity, compliance_date, next_due_date, responsible_user_id, status, observations, risk_level, renewable, reminder_days, int(me.get('id') or 0) or None, int(me.get('id') or 0) or None),
        )
        item_id = cur.lastrowid
        sync_document_deadlines(conn, 'petroleum')
        conn.commit(); conn.close()
        ctx.log_action(me, 'create_normativa', 'normativas', str(item_id), {'station_id': station_id, 'status': status, 'periodicity': periodicity})
        return jsonify({'ok': True, 'id': item_id})

    @app.patch('/api/normativas/<int:item_id>')
    @login_required
    @role_required('admin')
    def api_normativas_update(item_id: int):
        me = ctx.get_me() or {}
        data = request.get_json(silent=True) or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT station_id FROM normativas WHERE id=? AND brand='petroleum'", (item_id,))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        if me.get('role') != 'admin' and not ctx.can_access_station(me, int(row['station_id'] or 0)):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        allowed = {'station_id','catalog_id','norma_title','category','description','periodicity','compliance_date','next_due_date','responsible_user_id','status','observations','risk_level','renewable','reminder_days'}
        clean = {k: data.get(k) for k in allowed if k in data}
        if 'station_id' in clean and clean['station_id'] and me.get('role') != 'admin' and not ctx.can_access_station(me, int(clean['station_id'])):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        parts, params = [], []
        for key, value in clean.items():
            sval = str(value).strip() if value is not None else None
            if key == 'status' and sval not in NORMATIVA_STATUSES:
                continue
            if key == 'periodicity' and sval not in NORMATIVA_PERIODICITIES:
                continue
            if key == 'risk_level' and sval not in NORMATIVA_RISKS:
                continue
            parts.append(f"{key}=?")
            if key in {'station_id','catalog_id','responsible_user_id'}:
                params.append(int(value) if value else None)
            else:
                params.append(sval)
        parts += ['updated_at=CURRENT_TIMESTAMP', 'updated_by=?']
        params.append(int(me.get('id') or 0) or None)
        params.append(item_id)
        cur.execute(f"UPDATE normativas SET {', '.join(parts)} WHERE id=?", tuple(params))
        sync_document_deadlines(conn, 'petroleum')
        conn.commit(); conn.close()
        ctx.log_action(me, 'update_normativa', 'normativas', str(item_id), {'fields': sorted(clean.keys())})
        return jsonify({'ok': True})

    @app.post('/api/normativas/<int:item_id>/evidence')
    @login_required
    @role_required('admin')
    def api_normativas_evidence(item_id: int):
        me = ctx.get_me() or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT station_id FROM normativas WHERE id=? AND brand='petroleum'", (item_id,))
        row = cur.fetchone()
        if not row:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        if me.get('role') != 'admin' and not ctx.can_access_station(me, int(row['station_id'] or 0)):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        f = request.files.get('file')
        if not f or not (f.filename or '').strip():
            conn.close(); return jsonify({'ok': False, 'error': 'missing_file'}), 400
        rel = ctx.save_upload_checked(f, 'normativas', allowed_ext={'.pdf','.png','.jpg','.jpeg','.webp','.doc','.docx','.xls','.xlsx'}, limit_mb=25)
        cur.execute("UPDATE normativas SET evidence_path=?, updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=?", (rel, int(me.get('id') or 0) or None, item_id))
        sync_document_deadlines(conn, 'petroleum')
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'evidence_path': rel, 'evidence_url': '/uploads/' + rel})

    @app.get('/api/normativas/export.csv')
    @login_required
    @role_required('admin')
    def api_normativas_export_csv():
        me = ctx.get_me() or {}
        conn = get_conn(); cur = conn.cursor()
        sql = "SELECT n.folio, COALESCE(s.code,''), COALESCE(n.norma_title,''), COALESCE(n.category,''), COALESCE(n.periodicity,''), COALESCE(n.compliance_date,''), COALESCE(n.next_due_date,''), COALESCE(u.username,''), COALESCE(n.status,''), COALESCE(n.risk_level,''), COALESCE(n.observations,'') FROM normativas n LEFT JOIN stations s ON s.id=n.station_id LEFT JOIN users u ON u.id=n.responsible_user_id WHERE n.brand='petroleum'"
        params = []
        scope = _station_scope_ids(ctx, me)
        if scope:
            sql += ' AND n.station_id IN (%s)' % (','.join(['?'] * len(scope)))
            params.extend(sorted(scope))
        sql += ' ORDER BY n.id DESC'
        cur.execute(sql, tuple(params))
        rows = [list(r.values()) for r in cur.fetchall()]
        conn.close()
        return _csv_response('normativas_petroleum.csv', ['Folio','Estacion','Normativa','Categoria','Periodicidad','Cumplimiento','Proxima fecha','Responsable','Estatus','Riesgo','Observaciones'], rows)

    @app.get('/api/normativas/catalog')
    @login_required
    @role_required('admin')
    def api_normativas_catalog_list():
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, code, title, category, description, periodicity, default_risk, sort_order, is_active FROM normative_catalog WHERE brand='petroleum' ORDER BY sort_order ASC, id ASC")
        items = _apply_petroleum_catalog_branding([dict(r) for r in cur.fetchall()])
        conn.close()
        return jsonify({'ok': True, 'items': items})

    @app.post('/api/normativas/catalog')
    @login_required
    @role_required('admin')
    def api_normativas_catalog_create():
        data = request.get_json(silent=True) or {}
        code = (data.get('code') or '').strip().lower() or None
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'ok': False, 'error': 'missing_title'}), 400
        category = (data.get('category') or 'Seguridad').strip()
        description = (data.get('description') or '').strip()
        periodicity = (data.get('periodicity') or 'mensual').strip().lower()
        default_risk = (data.get('default_risk') or 'medio').strip().lower()
        sort_order = int(data.get('sort_order') or 0)
        conn = get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO normative_catalog (brand, code, title, category, description, periodicity, default_risk, sort_order, is_active) VALUES ('petroleum',?,?,?,?,?,?,?,1)", (code, title, category, description, periodicity, default_risk, sort_order))
        item_id = cur.lastrowid
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'id': item_id})


    @app.get('/admin/expedientes')
    @login_required
    @role_required('admin')
    def expediente_tramites_page():
        return redirect('/admin/document-center')

    @app.get('/petroleum/expedientes')
    @login_required
    @role_required('admin', 'jefe_estacion', 'operador', 'auditor', 'contador')
    def expediente_normativas_page():
        return render_template('petroleum/expedientes.html', expediente_area='normativas')

    @app.get('/api/expedientes/meta')
    @login_required
    def api_expedientes_meta():
        me = ctx.get_me() or {}
        area = (request.args.get('area') or 'tramites').strip().lower()
        brand = EXPEDIENTE_AREAS.get(area)
        if not brand:
            return jsonify({'ok': False, 'error': 'invalid_area'}), 400
        if area == 'tramites':
            return _tramites_disabled_json()
        stations = _stations_for_brand(brand)
        scope = _station_scope_ids(ctx, me)
        if scope:
            stations = [s for s in stations if int(s['id']) in scope]
        conn = get_conn(); cur = conn.cursor()
        sql_tpl, params_tpl = _exp_template_where(area, brand)
        cur.execute(sql_tpl, params_tpl)
        templates = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({'ok': True, 'brand': brand, 'area': area, 'area_label': EXPEDIENTE_LABELS.get(area, area.title()), 'stations': stations, 'templates': templates, 'statuses': EXPEDIENTE_STATUSES})

    @app.get('/api/expedientes/items')
    @login_required
    def api_expedientes_items():
        me = ctx.get_me() or {}
        area = (request.args.get('area') or 'tramites').strip().lower()
        if area == 'tramites':
            return _tramites_disabled_json()
        station_id = int(request.args.get('station_id') or 0) or None
        owner_name = (request.args.get('owner_name') or '').strip()
        brand, station, err = _exp_brand_and_scope(ctx, area, me, station_id, owner_name)
        if err:
            payload, code = err
            return jsonify(payload), code
        items = _exp_items_for_scope(area, brand, station_id, owner_name)
        return jsonify({'ok': True, 'items': items, 'summary': _exp_summary_from_items(items), 'scope_label': _exp_scope_label(station, owner_name), 'area': area, 'brand': brand})

    @app.post('/api/expedientes/templates')
    @login_required
    @role_required('admin')
    def api_expedientes_template_create():
        data = request.get_json(silent=True) or {}
        area = (data.get('area') or '').strip().lower()
        brand = EXPEDIENTE_AREAS.get(area)
        if not brand:
            return jsonify({'ok': False, 'error': 'invalid_area'}), 400
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'ok': False, 'error': 'missing_title'}), 400
        code = (data.get('code') or '').strip().lower() or None
        description = (data.get('description') or '').strip()
        is_required = 1 if str(data.get('is_required', '1')).lower() not in {'0','false','no'} else 0
        default_validity_days = int(data.get('default_validity_days') or 0) or None
        sort_order = int(data.get('sort_order') or 0)
        conn = get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO expediente_templates (brand, area, code, title, description, is_required, default_validity_days, sort_order, is_active) VALUES (?,?,?,?,?,?,?,?,1)", (brand, area, code, title, description, is_required, default_validity_days, sort_order))
        tid = cur.lastrowid
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'id': tid})

    @app.post('/api/expedientes/records')
    @login_required
    def api_expedientes_record_upsert():
        me = ctx.get_me() or {}
        data = request.get_json(silent=True) or {}
        area = (data.get('area') or '').strip().lower()
        if area == 'tramites':
            return _tramites_disabled_json()
        station_id = int(data.get('station_id') or 0) or None
        owner_name = (data.get('owner_name') or '').strip()
        brand, station, err = _exp_brand_and_scope(ctx, area, me, station_id, owner_name)
        if err:
            payload, code = err
            return jsonify(payload), code
        template_id = int(data.get('template_id') or 0) or None
        conn = get_conn(); cur = conn.cursor()
        tpl = None
        if template_id:
            cur.execute("SELECT id, title, default_validity_days, is_required FROM expediente_templates WHERE id=? AND brand=? AND area=?", (template_id, brand, area))
            tpl = cur.fetchone()
            if not tpl:
                conn.close(); return jsonify({'ok': False, 'error': 'template_not_found'}), 404
        scope_where, scope_params = _exp_scope_where(area, station_id, owner_name)
        existing = None
        if template_id:
            cur.execute(f"SELECT * FROM expediente_records er WHERE er.brand=? AND er.area=? AND er.template_id=? AND {scope_where} ORDER BY er.id DESC LIMIT 1", (brand, area, template_id, *scope_params))
            existing = cur.fetchone()
        record_id = int(data.get('record_id') or 0) or (int(existing['id']) if existing else None)
        title = (data.get('title') or (tpl['title'] if tpl else '') or '').strip()
        if not title:
            conn.close(); return jsonify({'ok': False, 'error': 'missing_title'}), 400
        status = (data.get('status') or 'faltante').strip().lower()
        if status not in EXPEDIENTE_STATUSES:
            status = 'faltante'
        issue_date = (data.get('issue_date') or '').strip() or None
        expiry_date = (data.get('expiry_date') or '').strip() or None
        notes = (data.get('notes') or '').strip()
        renewable = 0 if str(data.get('renewable', '1')).lower() in {'0','false','no'} else 1
        reminder_days = (data.get('reminder_days') or '60,30,15,7,3,1,0').strip()
        periodicity = (data.get('periodicity') or 'anual').strip().lower() or 'anual'
        validity = int((tpl['default_validity_days'] if tpl and tpl['default_validity_days'] else 0) or 0)
        if issue_date and not expiry_date and validity:
            try:
                expiry_date = (date.fromisoformat(issue_date[:10]) + timedelta(days=validity)).isoformat()
            except Exception:
                pass
        uid = int(me.get('id') or 0) or None
        if record_id:
            cur.execute("UPDATE expediente_records SET title=?, status=?, issue_date=?, expiry_date=?, notes=?, renewable=?, periodicity=?, reminder_days=?, updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=? AND brand=? AND area=?", (title, status, issue_date, expiry_date, notes, renewable, periodicity, reminder_days, uid, record_id, brand, area))
        else:
            cur.execute("INSERT INTO expediente_records (brand, area, station_id, owner_name, template_id, title, status, issue_date, expiry_date, notes, renewable, periodicity, reminder_days, created_by, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (brand, area, station_id, owner_name or None, template_id, title, status, issue_date, expiry_date, notes, renewable, periodicity, reminder_days, uid, uid))
            record_id = cur.lastrowid
        sync_document_deadlines(conn, brand)
        conn.commit(); conn.close()
        ctx.log_action(me, 'upsert_expediente_record', 'expediente_records', str(record_id), {'area': area, 'station_id': station_id, 'owner_name': owner_name, 'template_id': template_id, 'status': status})
        return jsonify({'ok': True, 'id': record_id})

    @app.post('/api/expedientes/<int:record_id>/file')
    @login_required
    def api_expedientes_file(record_id: int):
        me = ctx.get_me() or {}
        f = request.files.get('file')
        if not f or not (f.filename or '').strip():
            return jsonify({'ok': False, 'error': 'missing_file'}), 400
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM expediente_records WHERE id=?", (record_id,))
        rec = cur.fetchone()
        if not rec:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        area = (rec['area'] or '').strip().lower()
        if area == 'tramites':
            conn.close(); return _tramites_disabled_json()
        if area == 'normativas' and me.get('role') != 'admin' and rec['station_id'] and not ctx.can_access_station(me, int(rec['station_id'])):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        rel = ctx.save_upload_checked(f, f'expedientes/{area}', allowed_ext={'.pdf','.png','.jpg','.jpeg','.webp','.doc','.docx','.xls','.xlsx'}, limit_mb=25)
        next_ver = int(rec['version_count'] or 0) + 1
        cur.execute("UPDATE expediente_records SET current_file_path=?, version_count=?, status=CASE WHEN status='faltante' THEN 'vigente' ELSE status END, updated_at=CURRENT_TIMESTAMP, updated_by=? WHERE id=?", (rel, next_ver, int(me.get('id') or 0) or None, record_id))
        cur.execute("INSERT INTO expediente_versions (record_id, version_no, file_path, notes, uploaded_by) VALUES (?,?,?,?,?)", (record_id, next_ver, rel, (request.form.get('notes') or '').strip(), int(me.get('id') or 0) or None))
        sync_document_deadlines(conn, rec['brand'])
        conn.commit(); conn.close()
        ctx.log_action(me, 'upload_expediente_file', 'expediente_records', str(record_id), {'version': next_ver, 'path': rel})
        return jsonify({'ok': True, 'file_path': rel, 'file_url': '/uploads/' + rel, 'version_no': next_ver})

    @app.get('/api/expedientes/<int:record_id>/versions')
    @login_required
    def api_expedientes_versions(record_id: int):
        me = ctx.get_me() or {}
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT area, station_id FROM expediente_records WHERE id=?", (record_id,))
        rec = cur.fetchone()
        if not rec:
            conn.close(); return jsonify({'ok': False, 'error': 'not_found'}), 404
        area = (rec['area'] or '').strip().lower()
        if area == 'tramites':
            conn.close(); return _tramites_disabled_json()
        if area == 'normativas' and me.get('role') != 'admin' and rec['station_id'] and not ctx.can_access_station(me, int(rec['station_id'])):
            conn.close(); return jsonify({'ok': False, 'error': 'forbidden_station'}), 403
        cur.execute("SELECT ev.*, u.username AS uploaded_by_name FROM expediente_versions ev LEFT JOIN users u ON u.id=ev.uploaded_by WHERE ev.record_id=? ORDER BY ev.version_no DESC, ev.id DESC", (record_id,))
        versions = [dict(r) for r in cur.fetchall()]
        conn.close()
        for item in versions:
            item['file_url'] = '/uploads/' + item['file_path'] if item.get('file_path') else None
        return jsonify({'ok': True, 'items': versions})

from __future__ import annotations

import re

from db import get_conn

NORMATIVE_DEFAULTS = {
    'nom005': {
        'title': 'NOM-005', 'badge': 'NOM', 'tone': 'green', 'color': '#22C55E', 'order': 10, 'enabled': True,
        'icon': '⛽', 'description': 'Control operativo y documental para la NOM-005 en estaciones y procesos petrolíferos.',
    },
    'nom016': {
        'title': 'NOM-016', 'badge': 'NOM', 'tone': 'red', 'color': '#EF4444', 'order': 20, 'enabled': True,
        'icon': '🧪', 'description': 'Seguimiento técnico y evidencias para calidad de combustibles bajo NOM-016.',
    },
    'anexo3031': {
        'title': 'Anexo 30-31', 'badge': 'ANEXO', 'tone': 'black', 'color': '#111827', 'order': 30, 'enabled': True,
        'icon': '📁', 'description': 'Expediente regulatorio, anexos y trazabilidad documental por estación.',
    },
}

DEFAULT_BRAND_SETTINGS = {
    "consulting": {
        "display_name": "Consulting Oil & Gas",
        "subtitle": "Renewable Energy HME, S.A. de C.V.",
        "system_title": "CONSULTING • Work Log",
        "system_subtitle": "Plataforma corporativa para estaciones",
        "primary_color": "#86B821",
        "secondary_color": "#2C7BE5",
        "public_url": "https://consultinghme.com/",
        "support_email": "",
        "hero_title": "Sistema Corporativo de Gestión y Cumplimiento",
        "hero_text": "Plataforma interna para la gestión operativa, cumplimiento normativo y control documental de estaciones y proyectos energéticos.",
        "logo_path": "",
        "logo_square_path": "",
        "mail_provider": "auto",
        "ses_region": "",
        "ses_from": "",
        "ses_configuration_set": "",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "app_url": "",
        "whatsapp_webhook_url": "",
        "norms_nom005_title": "NOM-005",
        "norms_nom005_badge": "NOM",
        "norms_nom005_color": "#22C55E",
        "norms_nom005_order": "10",
        "norms_nom005_enabled": "1",
        "norms_nom005_icon": "⛽",
        "norms_nom005_description": "Control operativo y documental para la NOM-005 en estaciones y procesos petrolíferos.",
        "norms_nom016_title": "NOM-016",
        "norms_nom016_badge": "NOM",
        "norms_nom016_color": "#EF4444",
        "norms_nom016_order": "20",
        "norms_nom016_enabled": "1",
        "norms_nom016_icon": "🧪",
        "norms_nom016_description": "Seguimiento técnico y evidencias para calidad de combustibles bajo NOM-016.",
        "norms_anexo3031_title": "Anexo 30-31",
        "norms_anexo3031_badge": "ANEXO",
        "norms_anexo3031_color": "#111827",
        "norms_anexo3031_order": "30",
        "norms_anexo3031_enabled": "1",
        "norms_anexo3031_icon": "📁",
        "norms_anexo3031_description": "Expediente regulatorio, anexos y trazabilidad documental por estación.",
    },
    "petroleum": {
        "display_name": "Petroleum IU",
        "subtitle": "Oil & Gas Inspection Unit",
        "system_title": "PETROLEUM • Work Log",
        "system_subtitle": "Oil & Gas Inspection Unit",
        "primary_color": "#C8A24A",
        "secondary_color": "#7C3AED",
        "public_url": "https://petroleumiu.com/",
        "support_email": "",
        "hero_title": "Sistema Corporativo de Gestión y Cumplimiento",
        "hero_text": "Plataforma interna para la gestión operativa, cumplimiento normativo y control documental de estaciones y proyectos energéticos.",
        "logo_path": "",
        "logo_square_path": "",
        "mail_provider": "auto",
        "ses_region": "",
        "ses_from": "",
        "ses_configuration_set": "",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "app_url": "",
        "whatsapp_webhook_url": "",
        "norms_nom005_title": "NOM-005",
        "norms_nom005_badge": "NOM",
        "norms_nom005_color": "#22C55E",
        "norms_nom005_order": "10",
        "norms_nom005_enabled": "1",
        "norms_nom005_icon": "⛽",
        "norms_nom005_description": "Control operativo y documental para la NOM-005 en estaciones y procesos petrolíferos.",
        "norms_nom016_title": "NOM-016",
        "norms_nom016_badge": "NOM",
        "norms_nom016_color": "#EF4444",
        "norms_nom016_order": "20",
        "norms_nom016_enabled": "1",
        "norms_nom016_icon": "🧪",
        "norms_nom016_description": "Seguimiento técnico y evidencias para calidad de combustibles bajo NOM-016.",
        "norms_anexo3031_title": "Anexo 30-31",
        "norms_anexo3031_badge": "ANEXO",
        "norms_anexo3031_color": "#111827",
        "norms_anexo3031_order": "30",
        "norms_anexo3031_enabled": "1",
        "norms_anexo3031_icon": "📁",
        "norms_anexo3031_description": "Expediente regulatorio, anexos y trazabilidad documental por estación.",
    },
}


def get_branding_settings(brand: str | None = None) -> dict:
    b = (brand or "consulting").strip().lower()
    if b not in DEFAULT_BRAND_SETTINGS:
        b = "consulting"
    data = dict(DEFAULT_BRAND_SETTINGS[b])
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT key, value FROM branding_settings WHERE brand=?", (b,))
        for r in cur.fetchall():
            key = (r.get("key") or "").strip()
            if key:
                data[key] = r.get("value") or ""
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
    return data


def set_branding_settings(brand: str, values: dict) -> None:
    b = (brand or "consulting").strip().lower()
    if b not in DEFAULT_BRAND_SETTINGS:
        b = "consulting"
    conn = get_conn(); cur = conn.cursor()
    for key, value in (values or {}).items():
        cur.execute(
            "INSERT INTO branding_settings (brand, key, value, updated_at) VALUES (?,?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(brand, key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (b, str(key), str(value or "")),
        )
    conn.commit(); conn.close()


def get_setting_fallback(key: str, brand: str | None = None, default: str = "") -> str:
    key = (key or "").strip()
    if not key:
        return default
    brands = []
    if brand:
        brands.append((brand or "consulting").strip().lower())
    brands.extend([b for b in ("consulting", "petroleum") if b not in brands])
    try:
        conn = get_conn(); cur = conn.cursor()
        for b in brands:
            cur.execute("SELECT value FROM branding_settings WHERE brand=? AND key=?", (b, key))
            row = cur.fetchone()
            if row and (row.get("value") or "").strip() != "":
                conn.close()
                return (row.get("value") or "").strip()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
    return default



def _clean_title(value: str, default: str) -> str:
    value = (value or '').strip()
    return value or default


def _infer_badge(title: str, fallback: str = '') -> str:
    title = (title or '').strip()
    fallback = (fallback or '').strip()
    if not title:
        return fallback
    upper = title.upper()
    if upper.startswith('ANEXO'):
        return 'ANEXO'
    if upper.startswith('NOM'):
        return 'NOM'
    token = re.split(r"[\s\-_/]+", title, maxsplit=1)[0].strip(' .,:;')
    token = re.sub(r'[^A-Za-zÁÉÍÓÚÜÑ0-9]+', '', token)
    return (token[:12].upper() if token else fallback) or fallback


def _clean_int(value, default: int) -> int:
    try:
        return int(str(value or '').strip())
    except Exception:
        return int(default)


def _clean_bool(value, default: bool = True) -> bool:
    raw = str(value or '').strip().lower()
    if not raw:
        return default
    return raw in {'1', 'true', 'yes', 'on', 'si', 'sí'}


def _clean_color(value: str, default: str) -> str:
    raw = (value or '').strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}', raw):
        return raw.upper()
    return default.upper()


def _clean_icon(value: str, default: str) -> str:
    raw = (value or '').strip()
    if not raw:
        return default
    return raw[:8]


def _clean_description(value: str, default: str) -> str:
    raw = ' '.join(str(value or '').strip().split())
    return raw or default



def get_normative_config(brand: str | None = 'petroleum') -> dict:
    cfg = get_branding_settings(brand or 'petroleum')
    data = {}
    for code, meta in NORMATIVE_DEFAULTS.items():
        title_key = f'norms_{code}_title'
        badge_key = f'norms_{code}_badge'
        color_key = f'norms_{code}_color'
        order_key = f'norms_{code}_order'
        enabled_key = f'norms_{code}_enabled'
        icon_key = f'norms_{code}_icon'
        description_key = f'norms_{code}_description'
        title = _clean_title(cfg.get(title_key), meta['title'])
        badge = _clean_title(cfg.get(badge_key), _infer_badge(title, meta['badge']))
        data[code] = {
            'title': title,
            'badge': badge,
            'tone': meta['tone'],
            'color': _clean_color(cfg.get(color_key), meta['color']),
            'order': _clean_int(cfg.get(order_key), meta['order']),
            'enabled': _clean_bool(cfg.get(enabled_key), meta['enabled']),
            'icon': _clean_icon(cfg.get(icon_key), meta.get('icon', '•')),
            'description': _clean_description(cfg.get(description_key), meta.get('description', '')),
        }
    return data


def get_normative_items(brand: str | None = 'petroleum', visible_only: bool = False) -> list[dict]:
    items = []
    for code, meta in get_normative_config(brand).items():
        row = {'code': code, **meta}
        if visible_only and not row.get('enabled', True):
            continue
        items.append(row)
    items.sort(key=lambda item: (int(item.get('order') or 0), item.get('code') or ''))
    return items


def get_normative_titles_line(brand: str | None = 'petroleum') -> str:
    titles = [item['title'] for item in get_normative_items(brand, visible_only=True)]
    if not titles:
        titles = [item['title'] for item in get_normative_items(brand, visible_only=False)]
    if not titles:
        return ''
    if len(titles) == 1:
        return titles[0]
    if len(titles) == 2:
        return f"{titles[0]} y {titles[1]}"
    return ', '.join(titles[:-1]) + f" y {titles[-1]}"

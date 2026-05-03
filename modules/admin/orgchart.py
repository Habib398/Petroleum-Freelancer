from __future__ import annotations

import io
import math
import os
import uuid
from pathlib import Path
from typing import Any

from flask import abort, g, jsonify, redirect, render_template, request, send_file, session
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename

from db import get_conn
from services.brand import get_brand, set_brand, user_allows_brand

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageFilter = ImageFont = ImageOps = None

ALLOWED_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}

DEFAULT_CONSULTING_NODES = [
    {
        'node_type': 'person', 'parent_slug': None, 'slug': 'director-general', 'name': 'Usiel Hernández Cupido',
        'title': 'Director General', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1f6feb', 'sort_order': 10, 'photo_path': 'static/img/orgchart_consulting/usiel.png'
    },
    {
        'node_type': 'department', 'parent_slug': 'director-general', 'slug': 'consultores', 'name': 'Consultores',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#21c55d', 'sort_order': 20, 'photo_path': ''
    },
    {
        'node_type': 'department', 'parent_slug': 'director-general', 'slug': 'contaduria-rh', 'name': 'Jefe de Contaduría / RH',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#10b8c9', 'sort_order': 30, 'photo_path': ''
    },
    {
        'node_type': 'department', 'parent_slug': 'director-general', 'slug': 'area-sistemas', 'name': 'Área Sistemas',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#0f6bd6', 'sort_order': 40, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'jose-manuel', 'name': 'José Manuel López Hdez.',
        'title': 'Consultor', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 10, 'photo_path': 'static/img/orgchart_consulting/jose_manuel.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'aseal-cruz', 'name': 'Aseal Cruz Herrera',
        'title': 'Consultor', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 20, 'photo_path': 'static/img/orgchart_consulting/aseal_cruz.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'sergio-dominguez', 'name': 'Sergio Domínguez V.',
        'title': 'Consultor', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 30, 'photo_path': 'static/img/orgchart_consulting/sergio_dominguez.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'guillerno-castillo', 'name': 'Guillerno Castillo F.',
        'title': 'Consultor', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 40, 'photo_path': 'static/img/orgchart_consulting/guillerno_castillo.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'kevin-arias', 'name': 'Kevin Arias Ovando',
        'title': 'Consultor', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 50, 'photo_path': 'static/img/orgchart_consulting/kevin_arias.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'consultores', 'slug': 'musi-maresa', 'name': 'Musi Maresa Hidalgo M.',
        'title': 'Consultora', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1c8f48', 'sort_order': 60, 'photo_path': 'static/img/orgchart_consulting/musi_maresa.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'contaduria-rh', 'slug': 'nitzia-riquer', 'name': 'Nitzia Riquer Huesca',
        'title': 'Jefe de Contaduría / RH', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#10b8c9', 'sort_order': 10, 'photo_path': 'static/img/orgchart_consulting/nitzia.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'contaduria-rh', 'slug': 'subjefe-rh', 'name': 'Subjefe',
        'title': 'Subjefe', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#10b8c9', 'sort_order': 20, 'photo_path': 'static/img/orgchart_consulting/subjefe.png'
    },
    {
        'node_type': 'person', 'parent_slug': 'area-sistemas', 'slug': 'misael-sainz', 'name': 'Misael Sainz Reséndiz',
        'title': 'Área Sistemas', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#0f6bd6', 'sort_order': 10, 'photo_path': 'static/img/orgchart_consulting/misael.png'
    },

]

DEFAULT_PETROLEUM_NODES = [
    {
        'node_type': 'person', 'parent_slug': None, 'slug': 'alta-direccion', 'name': 'Alta Dirección',
        'title': 'Dirección General', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#d8a84f', 'sort_order': 5, 'photo_path': ''
    },
    {
        'node_type': 'department', 'parent_slug': 'alta-direccion', 'slug': 'gerente-calidad', 'name': 'Gerente de Calidad',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#7bb24b', 'sort_order': 10, 'photo_path': ''
    },
    {
        'node_type': 'department', 'parent_slug': 'alta-direccion', 'slug': 'unidad-inspeccion', 'name': 'Unidad de Inspección',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#7bb24b', 'sort_order': 20, 'photo_path': ''
    },
    {
        'node_type': 'department', 'parent_slug': 'alta-direccion', 'slug': 'tercer-autorizado', 'name': 'Tercer Autorizado',
        'title': '', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#7bb24b', 'sort_order': 30, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'daniel-bautista', 'name': 'Daniel Bautista Ramos',
        'title': 'Gerente Técnico', 'profession': 'Ing. Civil', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 10, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'marcial-diaz', 'name': 'Marcial Díaz Gutiérrez',
        'title': 'Gerente Técnico Sustituto', 'profession': 'Ing. en Electrónica', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 20, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'tercer-autorizado', 'slug': 'experto-tecnico', 'name': 'Pendiente de asignar',
        'title': 'Experto Técnico', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 10, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'tercer-autorizado', 'slug': 'responsable-tecnico', 'name': 'Pendiente de asignar',
        'title': 'Responsable Técnico', 'profession': '', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 20, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'karla-adauto', 'name': 'Karla Adauto Rivera',
        'title': 'Inspectora', 'profession': 'Ing. en Geología Ambiental', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 30, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'jose-olegario', 'name': 'José Olegario Aguilera Cupido',
        'title': 'Inspector', 'profession': 'Ing. Ambiental', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 40, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'axel-salomon', 'name': 'Axel Salomón Gómez Reyes',
        'title': 'Inspector', 'profession': 'Ing. en Geología Ambiental', 'email': '', 'phone': '',
        'accent_color': '#1d4c96', 'sort_order': 50, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'rosa-guadalupe', 'name': 'Rosa Guadalupe Calva Martínez',
        'title': 'Auxiliar de Inspección', 'profession': 'Ing. en Geología Ambiental', 'email': '', 'phone': '',
        'accent_color': '#d97c2f', 'sort_order': 60, 'photo_path': ''
    },
    {
        'node_type': 'person', 'parent_slug': 'unidad-inspeccion', 'slug': 'brayan-mayorga', 'name': 'Brayan Isaac Mayorga Martínez',
        'title': 'Apoyo Técnico', 'profession': 'Arquitecto en proceso', 'email': '', 'phone': '',
        'accent_color': '#d97c2f', 'sort_order': 70, 'photo_path': ''
    },
]


def register(app):
    import functools

    ctx = app.extensions['ctx']

    def page_login_required(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                return redirect('/login')
            return fn(*args, **kwargs)
        return wrapper

    def page_role_required(*roles):
        roles_set = set([r for r in roles if r])
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                me = ctx.get_me()
                if not me:
                    return redirect('/login')
                if roles_set and me.get('role') not in roles_set:
                    abort(403)
                return fn(*args, **kwargs)
            return wrapper
        return deco

    def page_require_brand(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            me = ctx.get_me()
            if not me:
                return redirect('/login')
            if me.get('role') == 'admin':
                return fn(*args, **kwargs)
            brand = get_brand()
            if not user_allows_brand(me, brand):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper

    def _ensure_tables():
        conn = get_conn(); cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS org_charts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            title TEXT NOT NULL,
            subtitle TEXT,
            style_name TEXT NOT NULL DEFAULT 'glass',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS org_chart_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chart_id INTEGER NOT NULL,
            parent_id INTEGER,
            node_type TEXT NOT NULL DEFAULT 'person',
            name TEXT NOT NULL,
            title TEXT,
            profession TEXT,
            email TEXT,
            phone TEXT,
            photo_path TEXT,
            accent_color TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            FOREIGN KEY(chart_id) REFERENCES org_charts(id) ON DELETE CASCADE,
            FOREIGN KEY(parent_id) REFERENCES org_chart_nodes(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_org_charts_brand ON org_charts(brand, is_active);
        CREATE INDEX IF NOT EXISTS idx_org_chart_nodes_chart ON org_chart_nodes(chart_id, parent_id, sort_order);
        """)
        conn.commit(); conn.close()

    def _fetch_chart(brand: str) -> dict[str, Any] | None:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM org_charts WHERE brand=? AND is_active=1 ORDER BY id DESC LIMIT 1", (brand,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def _fetch_nodes(chart_id: int) -> list[dict[str, Any]]:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT * FROM org_chart_nodes WHERE chart_id=? ORDER BY COALESCE(parent_id,0), sort_order ASC, id ASC",
            (int(chart_id),),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def _seed_consulting_chart_if_missing() -> dict[str, Any]:
        _ensure_tables()
        chart = _fetch_chart('consulting')
        if chart:
            return chart
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO org_charts (brand, title, subtitle, style_name, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
            ('consulting', 'Organigrama Consulting Oil & Gas', 'Renewable Energy HME, S.A. de C.V.', 'glass'),
        )
        chart_id = int(cur.lastrowid)
        id_map: dict[str, int] = {}
        for item in DEFAULT_CONSULTING_NODES:
            parent_id = id_map.get(item['parent_slug']) if item.get('parent_slug') else None
            cur.execute(
                """
                INSERT INTO org_chart_nodes
                (chart_id, parent_id, node_type, name, title, profession, email, phone, photo_path, accent_color, sort_order, is_visible, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                """,
                (
                    chart_id,
                    parent_id,
                    item['node_type'],
                    item['name'],
                    item.get('title') or '',
                    item.get('profession') or '',
                    item.get('email') or '',
                    item.get('phone') or '',
                    item.get('photo_path') or '',
                    item.get('accent_color') or '#1f6feb',
                    int(item.get('sort_order') or 0),
                ),
            )
            id_map[item['slug']] = int(cur.lastrowid)
        conn.commit(); conn.close()
        return _fetch_chart('consulting') or {}

    def _seed_petroleum_chart_if_missing() -> dict[str, Any]:
        _ensure_tables()
        chart = _fetch_chart('petroleum')
        if not chart:
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO org_charts (brand, title, subtitle, style_name, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                ('petroleum', 'Organigrama Petroleum Oil & Gas', 'Oil & Gas Inspection Unit, S.A. de C.V.', 'glass'),
            )
            conn.commit(); conn.close()
            chart = _fetch_chart('petroleum') or {}
        if not chart or not chart.get('id'):
            return chart or {}
        existing = _fetch_nodes(int(chart['id']))
        if existing:
            return chart
        conn = get_conn(); cur = conn.cursor()
        id_map: dict[str, int] = {}
        for item in DEFAULT_PETROLEUM_NODES:
            parent_id = id_map.get(item['parent_slug']) if item.get('parent_slug') else None
            cur.execute(
                """
                INSERT INTO org_chart_nodes
                (chart_id, parent_id, node_type, name, title, profession, email, phone, photo_path, accent_color, sort_order, is_visible, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                """,
                (
                    int(chart['id']),
                    parent_id,
                    item['node_type'],
                    item['name'],
                    item.get('title') or '',
                    item.get('profession') or '',
                    item.get('email') or '',
                    item.get('phone') or '',
                    item.get('photo_path') or '',
                    item.get('accent_color') or '#d69b3f',
                    int(item.get('sort_order') or 0),
                ),
            )
            id_map[item['slug']] = int(cur.lastrowid)
        conn.commit(); conn.close()
        return _fetch_chart('petroleum') or {}

    def _create_petroleum_base_chart() -> dict[str, Any]:
        return _seed_petroleum_chart_if_missing()

    def _chart_bundle(brand: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
        if brand == 'consulting':
            chart = _seed_consulting_chart_if_missing()
        else:
            chart = _seed_petroleum_chart_if_missing()
        nodes = _fetch_nodes(int(chart['id'])) if chart and chart.get('id') else []
        director = next((n for n in nodes if n.get('parent_id') is None and n.get('node_type') == 'person' and int(n.get('is_visible') or 0) == 1), None)
        departments = []
        if chart and chart.get('id'):
            for node in nodes:
                if node.get('node_type') != 'department' or int(node.get('is_visible') or 0) != 1:
                    continue
                children = [
                    child for child in nodes
                    if child.get('parent_id') == node.get('id') and int(child.get('is_visible') or 0) == 1
                ]
                children.sort(key=lambda c: (int(c.get('sort_order') or 0), int(c.get('id') or 0)))
                node['children'] = children
                departments.append(node)
        departments.sort(key=lambda d: (int(d.get('sort_order') or 0), int(d.get('id') or 0)))
        return chart, nodes, director, departments

    def _petroleum_layout(chart: dict[str, Any] | None, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        by_name = {str(n.get('name') or '').strip().lower(): n for n in nodes}
        def find(name: str):
            return by_name.get(name.strip().lower())
        director = next((n for n in nodes if n.get('parent_id') is None and int(n.get('is_visible') or 0) == 1), None)
        unit = find('Unidad de Inspección')
        third = find('Tercer Autorizado')
        quality = find('Gerente de Calidad')
        inspectors = [
            n for n in nodes
            if int(n.get('is_visible') or 0) == 1 and str(n.get('title') or '').strip().lower() in {'inspectora', 'inspector'}
        ]
        support = [
            n for n in nodes
            if int(n.get('is_visible') or 0) == 1 and str(n.get('title') or '').strip().lower() in {'auxiliar de inspección', 'apoyo técnico'}
        ]
        managers = [
            n for n in nodes
            if int(n.get('is_visible') or 0) == 1 and str(n.get('title') or '').strip().lower() in {'gerente técnico', 'gerente técnico sustituto'}
        ]
        third_roles = [
            n for n in nodes
            if int(n.get('is_visible') or 0) == 1 and str(n.get('title') or '').strip().lower() in {'experto técnico', 'responsable técnico'}
        ]
        managers.sort(key=lambda n: (int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        inspectors.sort(key=lambda n: (int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        support.sort(key=lambda n: (int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        third_roles.sort(key=lambda n: (int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        general_units = [
            {
                'name': 'Unidad de Inspección',
                'accent': '#7bb24b',
                'items': ['Estaciones de Servicio', 'Calidad de los Petrolíferos', 'Gas L.P.', 'Control Volumétrico'],
            },
            {
                'name': 'Tercer Autorizado',
                'accent': '#7bb24b',
                'items': ['Expendio simultáneo', 'Evaluaciones Técnicas SASISOPA', 'Auditoría Externa SASISOPA'],
            },
        ]
        return {
            'title': (chart or {}).get('title') or 'Organigrama Petroleum Oil & Gas',
            'subtitle': (chart or {}).get('subtitle') or 'Oil & Gas Inspection Unit, S.A. de C.V.',
            'director': director,
            'general_units': general_units,
            'quality': quality,
            'unit': unit,
            'third': third,
            'managers': managers,
            'third_roles': third_roles,
            'inspectors': inspectors,
            'support': support,
        }

    def _save_photo(file_storage, brand: str, node_id: int) -> str | None:
        if not file_storage or not (file_storage.filename or '').strip():
            return None
        ext = os.path.splitext(file_storage.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            return None
        fname = secure_filename(file_storage.filename or f'foto{ext}')
        base_name = os.path.splitext(fname)[0][:40] or 'foto'
        rel_dir = Path('orgchart') / brand / str(node_id)
        abs_dir = ctx.upload_dir / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)
        rel_path = rel_dir / f"{base_name}_{uuid.uuid4().hex[:8]}{ext}"
        get_storage().save_upload(file_storage, rel_path.as_posix())
        return rel_path.as_posix()

    def _resolve_asset_path(photo_path: str | None) -> Path | None:
        if not photo_path:
            return None
        rel = str(photo_path).replace('\\', '/').strip('/')
        if rel.startswith('static/'):
            candidate = Path(app.root_path) / rel
        else:
            candidate = get_storage().ensure_local(rel)
        return candidate if candidate.exists() else None

    def _hex_to_rgba(value: str | None, alpha: int = 255) -> tuple[int, int, int, int]:
        raw = (value or '').strip().lstrip('#')
        if len(raw) == 3:
            raw = ''.join(ch * 2 for ch in raw)
        if len(raw) != 6:
            raw = '1f6feb'
        try:
            return tuple(int(raw[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)
        except Exception:
            return (31, 111, 235, alpha)

    def _mix(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
        ratio = max(0.0, min(1.0, float(ratio)))
        return tuple(int(rgb_a[i] * (1 - ratio) + rgb_b[i] * ratio) for i in range(3))

    def _font_candidates(bold: bool) -> list[str]:
        if os.name == 'nt':
            return [
                r'C:\\Windows\\Fonts\\segoeuib.ttf' if bold else r'C:\\Windows\\Fonts\\segoeui.ttf',
                r'C:\\Windows\\Fonts\\arialbd.ttf' if bold else r'C:\\Windows\\Fonts\\arial.ttf',
            ]
        return [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        ]

    def _load_font(size: int, bold: bool = False):
        if ImageFont is None:
            return None
        for candidate in _font_candidates(bold):
            try:
                if os.path.exists(candidate):
                    return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _text(draw, xy: tuple[int, int], text: str, font, fill, anchor: str | None = None):
        if not text:
            return
        kwargs = {'fill': fill, 'font': font}
        if anchor:
            kwargs['anchor'] = anchor
        draw.text(xy, text, **kwargs)

    def _fit_text(draw, text: str, max_width: int, start_size: int, min_size: int = 14, bold: bool = False):
        text = text or ''
        size = start_size
        font = _load_font(size, bold)
        while size > min_size and draw.textbbox((0, 0), text, font=font)[2] > max_width:
            size -= 1
            font = _load_font(size, bold)
        return font

    def _truncate(draw, text: str, max_width: int, font) -> str:
        text = text or '—'
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        suffix = '…'
        out = text
        while out and draw.textbbox((0, 0), out + suffix, font=font)[2] > max_width:
            out = out[:-1]
        return (out + suffix) if out else suffix

    def _cover_image(src: Image.Image, size: tuple[int, int]) -> Image.Image:
        return ImageOps.fit(src.convert('RGBA'), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))

    def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
        mask = Image.new('L', size, 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
        return mask

    def _add_blur_glow(base: Image.Image, box: tuple[int, int, int, int], color: tuple[int, int, int, int], blur_radius: int) -> None:
        overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
        o = ImageDraw.Draw(overlay)
        o.ellipse(box, fill=color)
        overlay = overlay.filter(ImageFilter.GaussianBlur(blur_radius))
        base.alpha_composite(overlay)

    def _draw_glass_card(base: Image.Image, rect: tuple[int, int, int, int], accent: str, photo_path: str | None, title: str, name: str,
                         profession: str, email: str, phone: str, director: bool = False) -> None:
        x1, y1, x2, y2 = rect
        w, h = x2 - x1, y2 - y1
        radius = 36 if director else 28
        accent_rgba = _hex_to_rgba(accent, 255)
        accent_rgb = accent_rgba[:3]
        overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        glass_fill = (10, 20, 42, 182)
        glass_edge = (255, 255, 255, 32)
        odraw.rounded_rectangle(rect, radius=radius, fill=glass_fill, outline=glass_edge, width=2)
        odraw.rounded_rectangle((x1 + 1, y1 + 1, x2 - 1, y1 + 62), radius=radius, fill=(255, 255, 255, 18))
        odraw.rounded_rectangle((x1 + 14, y1 + 14, x1 + w - 14, y1 + h - 14), radius=max(16, radius - 10), outline=(255, 255, 255, 22), width=1)
        glow_color = accent_rgb + (110,)
        _add_blur_glow(overlay, (x1 - 30, y1 - 10, x2 + 30, y1 + 140), glow_color, 36)
        base.alpha_composite(overlay)
        draw = ImageDraw.Draw(base)

        photo_h = 220 if director else 138
        photo_box = (x1 + 22, y1 + 24, x2 - 22, y1 + 24 + photo_h)
        ppath = _resolve_asset_path(photo_path)
        if ppath and Image is not None:
            try:
                photo = Image.open(ppath).convert('RGBA')
                photo = _cover_image(photo, (photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]))
                mask = _round_mask((photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]), 28 if director else 22)
                layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
                layer.paste(photo, photo_box[:2], mask)
                base.alpha_composite(layer)
            except Exception:
                draw.rounded_rectangle(photo_box, radius=24, fill=(255, 255, 255, 26))
        else:
            draw.rounded_rectangle(photo_box, radius=24, fill=(255, 255, 255, 26))
            init_font = _load_font(58 if director else 44, True)
            _text(draw, ((photo_box[0] + photo_box[2]) // 2, (photo_box[1] + photo_box[3]) // 2), (name or '?')[:1], init_font, (235, 243, 255, 240), anchor='mm')

        chip_h = 46 if director else 36
        chip_y = photo_box[3] - (24 if director else 18)
        chip_box = (x1 + 46, chip_y, x2 - 46, chip_y + chip_h)
        chip_fill = _mix(accent_rgb, (255, 255, 255), 0.12) + (240,)
        chip_fill2 = _mix(accent_rgb, (0, 0, 0), 0.28) + (250,)
        chip_layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
        cdraw = ImageDraw.Draw(chip_layer)
        cdraw.rounded_rectangle(chip_box, radius=20, fill=chip_fill, outline=(255, 255, 255, 34), width=1)
        cdraw.rectangle((chip_box[0], chip_box[1] + chip_h // 2, chip_box[2], chip_box[3]), fill=chip_fill2)
        base.alpha_composite(chip_layer)
        chip_font = _fit_text(draw, title or 'Puesto', chip_box[2] - chip_box[0] - 30, 22 if director else 18, 12, True)
        _text(draw, ((chip_box[0] + chip_box[2]) // 2, chip_box[1] + chip_h // 2 + 1), (title or 'Puesto').upper(), chip_font, (247, 250, 255, 255), anchor='mm')

        name_font = _fit_text(draw, name or 'Sin nombre', w - 70, 34 if director else 24, 15, True)
        name_y = chip_box[3] + (34 if director else 26)
        _text(draw, ((x1 + x2) // 2, name_y), name or 'Sin nombre', name_font, (244, 248, 255, 255), anchor='mm')

        label_font = _load_font(13, True)
        value_font = _load_font(16, False)
        rows = [
            ('PROFESIÓN', profession or '—'),
            ('CORREO', email or '—'),
            ('TELÉFONO', phone or '—'),
        ]
        row_h = 34 if director else 30
        row_x = x1 + 22
        row_w = w - 44
        meta_y = name_y + (32 if director else 24)
        for idx, (label, value) in enumerate(rows):
            ry = meta_y + idx * (row_h + 8)
            row_layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
            rdraw = ImageDraw.Draw(row_layer)
            rdraw.rounded_rectangle((row_x, ry, row_x + row_w, ry + row_h), radius=16, fill=(255, 255, 255, 16), outline=(255, 255, 255, 20), width=1)
            base.alpha_composite(row_layer)
            _text(draw, (row_x + 14, ry + row_h // 2 + 1), label, label_font, (166, 193, 231, 245), anchor='lm')
            safe_value = _truncate(draw, value, row_w - 126, value_font)
            _text(draw, (row_x + 114, ry + row_h // 2 + 1), safe_value, value_font, (241, 246, 255, 255), anchor='lm')

    def _render_orgchart_image(brand: str, chart: dict[str, Any], director: dict[str, Any], departments: list[dict[str, Any]]):
        if Image is None or not director:
            raise RuntimeError('PIL no está disponible para renderizar el organigrama.')
        width = 1900
        margin = 80
        dep_gap = 28
        dep_count = max(1, len(departments) or 1)
        dep_width = int((width - margin * 2 - dep_gap * (dep_count - 1)) / dep_count)
        card_gap = 18
        compact_card_h = 292
        title_h = 72
        dep_heights = []
        for dep in departments:
            children = dep.get('children') or []
            rows = max(1, math.ceil(len(children) / 2))
            dep_heights.append(title_h + 26 + rows * compact_card_h + max(0, rows - 1) * card_gap)
        stage_bottom = max(dep_heights) if dep_heights else 380
        height = 250 + 420 + 54 + stage_bottom + 110
        img = Image.new('RGBA', (width, height), (5, 11, 24, 255))
        bg = Image.new('RGBA', img.size, (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(bg)
        top_rgb = (4, 11, 24)
        bottom_rgb = (10, 18, 36)
        if brand == 'petroleum':
            top_rgb = (7, 12, 26)
            bottom_rgb = (16, 22, 36)
        for y in range(height):
            ratio = y / max(1, height - 1)
            line = _mix(top_rgb, bottom_rgb, ratio)
            bdraw.line((0, y, width, y), fill=line + (255,))
        img.alpha_composite(bg)
        _add_blur_glow(img, (-160, 80, 620, 780), ((36, 201, 142, 120) if brand == 'consulting' else (71, 150, 255, 90)), 80)
        _add_blur_glow(img, (width - 700, 40, width + 120, 760), ((46, 157, 255, 90) if brand == 'consulting' else (224, 168, 69, 120)), 86)
        _add_blur_glow(img, (width // 2 - 260, 120, width // 2 + 260, 520), (255, 255, 255, 22), 70)
        draw = ImageDraw.Draw(img)
        for offset in range(4):
            alpha = 44 - offset * 8
            draw.arc((-120, 210 + offset * 20, width + 120, height + 180 + offset * 20), 192, 344, fill=(255, 255, 255, alpha), width=2)

        logo_path = Path(app.root_path) / ('static/img/consulting-logo-full.png' if brand == 'consulting' else 'static/img/petroleum-logo-full.png')
        if logo_path.exists() and Image is not None:
            try:
                logo = Image.open(logo_path).convert('RGBA')
                max_w, max_h = 580, 120
                scale = min(max_w / max(1, logo.width), max_h / max(1, logo.height))
                logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.Resampling.LANCZOS)
                lx = (width - logo.width) // 2
                img.alpha_composite(logo, (lx, 36))
            except Exception:
                pass
        title_font = _load_font(42, True)
        subtitle_font = _load_font(24, False)
        _text(draw, (width // 2, 176), chart.get('title') or 'Organigrama', title_font, (244, 247, 255, 255), anchor='mm')
        _text(draw, (width // 2, 216), chart.get('subtitle') or '', subtitle_font, (176, 197, 228, 255), anchor='mm')

        director_rect = (width // 2 - 230, 250, width // 2 + 230, 660)
        _draw_glass_card(
            img, director_rect, director.get('accent_color') or '#1f6feb', director.get('photo_path'),
            director.get('title') or 'Dirección', director.get('name') or 'Sin nombre',
            director.get('profession') or '', director.get('email') or '', director.get('phone') or '', director=True,
        )

        dep_y = 740
        center_x = width // 2
        line_color = (176, 202, 244, 118)
        draw.line((center_x, director_rect[3], center_x, dep_y - 46), fill=line_color, width=3)
        if departments:
            dep_centers = []
            for index in range(len(departments)):
                dep_left = margin + index * (dep_width + dep_gap)
                dep_centers.append(dep_left + dep_width // 2)
            if dep_centers:
                draw.line((dep_centers[0], dep_y - 46, dep_centers[-1], dep_y - 46), fill=line_color, width=3)
            for dep in departments:
                pass
        dep_font = _fit_text(draw, 'Área', dep_width - 40, 26, 18, True)
        for index, dep in enumerate(departments):
            dep_left = margin + index * (dep_width + dep_gap)
            dep_center = dep_left + dep_width // 2
            draw.line((dep_center, dep_y - 46, dep_center, dep_y), fill=line_color, width=3)
            title_box = (dep_left + 10, dep_y, dep_left + dep_width - 10, dep_y + title_h)
            accent = dep.get('accent_color') or ('#1f6feb' if brand == 'consulting' else '#d69b3f')
            title_rgb = _hex_to_rgba(accent, 255)[:3]
            overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            odraw.rounded_rectangle(title_box, radius=22, fill=(_mix(title_rgb, (255, 255, 255), 0.14) + (238,)), outline=(255, 255, 255, 28), width=1)
            img.alpha_composite(overlay)
            font = _fit_text(draw, dep.get('name') or 'Área', dep_width - 60, 24, 16, True)
            _text(draw, ((title_box[0] + title_box[2]) // 2, (title_box[1] + title_box[3]) // 2 + 1), (dep.get('name') or 'Área').upper(), font, (248, 251, 255, 255), anchor='mm')

            child_y = dep_y + title_h + 26
            children = dep.get('children') or []
            for child_index, child in enumerate(children):
                row = child_index // 2
                col = child_index % 2
                child_w = int((dep_width - 18) / 2) - 10
                if len(children) == 1:
                    child_w = dep_width - 40
                    cx = dep_left + 20
                else:
                    cx = dep_left + 10 + col * (child_w + 18)
                cy = child_y + row * (compact_card_h + card_gap)
                child_rect = (cx, cy, cx + child_w, cy + compact_card_h)
                connector_x = cx + child_w // 2
                draw.line((dep_center, title_box[3], dep_center, cy - 12), fill=(163, 189, 255, 88), width=2)
                draw.line((dep_center, cy - 12, connector_x, cy - 12), fill=(163, 189, 255, 88), width=2)
                draw.line((connector_x, cy - 12, connector_x, cy), fill=(163, 189, 255, 88), width=2)
                _draw_glass_card(
                    img, child_rect, child.get('accent_color') or accent, child.get('photo_path'),
                    child.get('title') or dep.get('name') or 'Puesto', child.get('name') or 'Sin nombre',
                    child.get('profession') or '', child.get('email') or '', child.get('phone') or '', director=False,
                )

        footer_font = _load_font(22, False)
        footer_text = 'Diseño Glass Premium · editable por administrador · vista solo lectura para staff'
        _text(draw, (width // 2, height - 42), footer_text, footer_font, (175, 194, 222, 220), anchor='mm')
        return img.convert('RGB')

    def _export_chart_png(brand: str, chart: dict[str, Any], director: dict[str, Any], departments: list[dict[str, Any]]) -> io.BytesIO:
        poster = _render_orgchart_image(brand, chart, director, departments)
        bio = io.BytesIO()
        poster.save(bio, format='PNG', optimize=True)
        bio.seek(0)
        return bio

    def _poster_to_pdf(poster) -> io.BytesIO:
        png_io = io.BytesIO()
        poster.save(png_io, format='PNG', optimize=True)
        png_io.seek(0)
        pdf_io = io.BytesIO()
        img_w, img_h = poster.size
        points_per_px = 72.0 / 150.0
        margin = 18
        draw_w = img_w * points_per_px
        draw_h = img_h * points_per_px
        page_w = draw_w + margin * 2
        page_h = draw_h + margin * 2
        pdf = canvas.Canvas(pdf_io, pagesize=(page_w, page_h), pageCompression=1)
        img_reader = ImageReader(png_io)
        pdf.drawImage(img_reader, margin, margin, width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')
        pdf.showPage()
        pdf.save()
        pdf_io.seek(0)
        return pdf_io

    def _export_chart_pdf(brand: str, chart: dict[str, Any], director: dict[str, Any], departments: list[dict[str, Any]]) -> io.BytesIO:
        poster = _render_orgchart_image(brand, chart, director, departments)
        return _poster_to_pdf(poster)

    def _draw_small_panel(base: Image.Image, rect: tuple[int, int, int, int], accent: str, title: str, name: str, profession: str = '') -> None:
        x1, y1, x2, y2 = rect
        accent_rgb = _hex_to_rgba(accent, 255)[:3]
        overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rounded_rectangle(rect, radius=24, fill=(11, 20, 42, 220), outline=(255, 255, 255, 28), width=2)
        odraw.rounded_rectangle((x1 + 10, y1 + 10, x2 - 10, y1 + 56), radius=18, fill=(_mix(accent_rgb, (255, 255, 255), 0.08) + (235,)), outline=(255,255,255,18), width=1)
        base.alpha_composite(overlay)
        draw = ImageDraw.Draw(base)
        tfont = _fit_text(draw, title or 'Puesto', x2 - x1 - 30, 24, 14, True)
        _text(draw, ((x1 + x2) // 2, y1 + 34), title or 'Puesto', tfont, (244, 248, 255, 255), anchor='mm')
        nfont = _fit_text(draw, name or 'Pendiente', x2 - x1 - 40, 28, 16, True)
        _text(draw, ((x1 + x2) // 2, y1 + 92), name or 'Pendiente de asignar', nfont, (244, 248, 255, 255), anchor='mm')
        if profession:
            pfont = _fit_text(draw, profession, x2 - x1 - 36, 20, 12, False)
            _text(draw, ((x1 + x2) // 2, y1 + 132), profession, pfont, (184, 202, 228, 255), anchor='mm')

    def _draw_title_box(base: Image.Image, rect: tuple[int, int, int, int], fill_hex: str, text_value: str, text_color=(248,251,255,255)) -> None:
        overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        fill_rgb = _hex_to_rgba(fill_hex, 255)[:3]
        odraw.rounded_rectangle(rect, radius=22, fill=fill_rgb + (230,), outline=(255,255,255,28), width=2)
        base.alpha_composite(overlay)
        draw = ImageDraw.Draw(base)
        font = _fit_text(draw, text_value, rect[2] - rect[0] - 24, 34, 16, True)
        _text(draw, ((rect[0]+rect[2])//2, (rect[1]+rect[3])//2 + 1), text_value, font, text_color, anchor='mm')

    def _render_petroleum_orgchart_image(chart: dict[str, Any], petro: dict[str, Any]):
        if Image is None:
            raise RuntimeError('PIL no está disponible para renderizar el organigrama.')
        width, height = 1800, 2940
        img = Image.new('RGBA', (width, height), (8, 14, 28, 255))
        bg = Image.new('RGBA', img.size, (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(bg)
        top_rgb = (8, 14, 28)
        bottom_rgb = (18, 25, 42)
        for y in range(height):
            ratio = y / max(1, height - 1)
            line = _mix(top_rgb, bottom_rgb, ratio)
            bdraw.line((0, y, width, y), fill=line + (255,))
        img.alpha_composite(bg)
        _add_blur_glow(img, (-200, 80, 640, 820), (48, 130, 255, 90), 90)
        _add_blur_glow(img, (width - 760, 0, width + 140, 760), (220, 168, 69, 110), 100)
        _add_blur_glow(img, (width//2 - 320, 1000, width//2 + 320, 1680), (255,255,255,18), 70)
        draw = ImageDraw.Draw(img)
        panel_fill = (12, 22, 44, 205)
        panel_outline = (255,255,255,30)

        def panel(rect):
            overlay = Image.new('RGBA', img.size, (0,0,0,0))
            od = ImageDraw.Draw(overlay)
            od.rounded_rectangle(rect, radius=36, fill=panel_fill, outline=panel_outline, width=2)
            img.alpha_composite(overlay)

        # header logo
        logo_path = Path(app.root_path) / 'static/img/petroleum-logo-full.png'
        if logo_path.exists() and Image is not None:
            try:
                logo = Image.open(logo_path).convert('RGBA')
                scale = min(620 / max(1, logo.width), 120 / max(1, logo.height))
                logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.Resampling.LANCZOS)
                img.alpha_composite(logo, ((width - logo.width) // 2, 28))
            except Exception:
                pass
        title_font = _load_font(40, True)
        subtitle_font = _load_font(22, False)
        _text(draw, (width // 2, 170), chart.get('title') or 'Organigrama Petroleum Oil & Gas', title_font, (244,247,255,255), anchor='mm')
        _text(draw, (width // 2, 210), chart.get('subtitle') or 'Oil & Gas Inspection Unit, S.A. de C.V.', subtitle_font, (184,202,228,255), anchor='mm')

        # general panel
        general_rect = (70, 250, width - 70, 930)
        panel(general_rect)
        kicker_font = _load_font(22, True)
        h2_font = _load_font(34, True)
        _text(draw, (general_rect[0] + 42, general_rect[1] + 48), 'ANEXO A', kicker_font, (220, 168, 69, 255), anchor='lm')
        _text(draw, (general_rect[0] + 42, general_rect[1] + 94), 'Organigrama General', h2_font, (244,247,255,255), anchor='lm')
        company_box = (width//2 - 320, general_rect[1] + 150, width//2 + 320, general_rect[1] + 260)
        _draw_title_box(img, company_box, '#d8a84f', 'Petroleum Oil & Gas Inspection Unit, S.A. de C.V.', text_color=(17,24,39,255))
        line_color = (176, 202, 244, 130)
        center_x = width // 2
        draw.line((center_x, company_box[3], center_x, general_rect[1] + 340), fill=line_color, width=3)
        left_center = width//2 - 400
        right_center = width//2 + 400
        draw.line((left_center, general_rect[1] + 340, right_center, general_rect[1] + 340), fill=line_color, width=3)
        branch_y = general_rect[1] + 340
        item_y = general_rect[1] + 470
        for idx, branch in enumerate(petro.get('general_units') or []):
            bx = left_center if idx == 0 else right_center
            branch_box = (bx - 165, branch_y, bx + 165, branch_y + 94)
            _draw_title_box(img, branch_box, branch.get('accent') or '#7bb24b', branch.get('name') or 'Área')
            draw.line((bx, general_rect[1] + 340, bx, branch_box[1]), fill=line_color, width=3)
            items = branch.get('items') or []
            item_gap = 18
            count = len(items) or 1
            total_w = count * 180 + (count - 1) * item_gap
            start_x = bx - total_w // 2
            item_line_y = item_y - 34
            draw.line((start_x + 90, item_line_y, start_x + total_w - 90, item_line_y), fill=line_color, width=3)
            draw.line((bx, branch_box[3], bx, item_line_y), fill=line_color, width=3)
            for i, item in enumerate(items):
                ix1 = start_x + i * (180 + item_gap)
                rect = (ix1, item_y, ix1 + 180, item_y + 110)
                draw.line((ix1 + 90, item_line_y, ix1 + 90, item_y), fill=line_color, width=3)
                overlay = Image.new('RGBA', img.size, (0,0,0,0))
                od = ImageDraw.Draw(overlay)
                od.rounded_rectangle(rect, radius=22, fill=(243, 247, 252, 235), outline=(160, 176, 198, 255), width=2)
                img.alpha_composite(overlay)
                font = _fit_text(draw, item, 156, 24, 14, True)
                # simple multiline wrap
                words=item.split()
                lines=[]
                current=''
                for w in words:
                    test=(current+' '+w).strip()
                    if draw.textbbox((0,0), test, font=font)[2] <= 150 or not current:
                        current=test
                    else:
                        lines.append(current); current=w
                if current: lines.append(current)
                yy = rect[1] + 34 - (len(lines)-1)*16
                for line in lines[:3]:
                    _text(draw, ((rect[0]+rect[2])//2, yy), line, font, (25, 33, 48, 255), anchor='mm')
                    yy += 32

        # functional panel
        func_rect = (70, 990, width - 70, height - 70)
        panel(func_rect)
        _text(draw, (func_rect[0] + 42, func_rect[1] + 48), 'ANEXO B', kicker_font, (220, 168, 69, 255), anchor='lm')
        _text(draw, (func_rect[0] + 42, func_rect[1] + 94), 'Organigrama Funcional', h2_font, (244,247,255,255), anchor='lm')
        top_box = (width//2 - 170, func_rect[1] + 150, width//2 + 170, func_rect[1] + 236)
        _draw_title_box(img, top_box, '#d8a84f', 'Alta Dirección')
        y_green = func_rect[1] + 310
        green_centers = [width//2 - 420, width//2, width//2 + 420]
        green_labels = [ (petro.get('quality') or {}).get('name') or 'Gerente de Calidad', (petro.get('unit') or {}).get('name') or 'Unidad de Inspección', (petro.get('third') or {}).get('name') or 'Tercer Autorizado']
        draw.line((width//2, top_box[3], width//2, y_green - 28), fill=line_color, width=3)
        draw.line((green_centers[0], y_green - 28, green_centers[-1], y_green - 28), fill=line_color, width=3)
        for cx, label in zip(green_centers, green_labels):
            draw.line((cx, y_green - 28, cx, y_green), fill=line_color, width=3)
            _draw_title_box(img, (cx - 170, y_green, cx + 170, y_green + 90), '#7bb24b', label)

        # manager and upper technical roles with photo cards
        row_y = y_green + 150
        managers = petro.get('managers') or []
        third_roles = petro.get('third_roles') or []
        top_people = managers + third_roles
        card_w, card_h = 320, 308
        top_centers = [width//2 - 540, width//2 - 180, width//2 + 180, width//2 + 540][:len(top_people)]
        if managers:
            manager_centers = top_centers[:len(managers)]
            draw.line((green_centers[1], y_green + 90, green_centers[1], row_y - 30), fill=line_color, width=3)
            if manager_centers:
                draw.line((manager_centers[0], row_y - 30, manager_centers[-1], row_y - 30), fill=line_color, width=3)
        if third_roles:
            third_centers = top_centers[len(managers):len(managers) + len(third_roles)]
            draw.line((green_centers[2], y_green + 90, green_centers[2], row_y - 30), fill=line_color, width=3)
            if third_centers:
                draw.line((third_centers[0], row_y - 30, third_centers[-1], row_y - 30), fill=line_color, width=3)
        for cx, person in zip(top_centers, top_people):
            rect = (cx - card_w // 2, row_y, cx + card_w // 2, row_y + card_h)
            draw.line((cx, row_y - 30, cx, row_y), fill=line_color, width=3)
            _draw_glass_card(
                img,
                rect,
                person.get('accent_color') or '#1d4c96',
                person.get('photo_path'),
                person.get('title') or 'Puesto',
                person.get('name') or 'Pendiente de asignar',
                person.get('profession') or '',
                person.get('email') or '',
                person.get('phone') or '',
                director=False,
            )

        inspectors_head = (width//2 - 240, row_y + card_h + 90, width//2 + 240, row_y + card_h + 166)
        _draw_title_box(img, inspectors_head, '#d8a84f', 'Equipo de inspección y apoyo')
        people = (petro.get('inspectors') or []) + (petro.get('support') or [])
        top_people = people[:3]
        bottom_people = people[3:]
        top_y = inspectors_head[3] + 54
        card_w, card_h = 360, 360
        top_centers = [width//2 - 420, width//2, width//2 + 420][:len(top_people)]
        head_center = width//2
        if top_people:
            draw.line((head_center, inspectors_head[3], head_center, top_y - 28), fill=line_color, width=3)
            draw.line((top_centers[0], top_y - 28, top_centers[-1], top_y - 28), fill=line_color, width=3)
        top_rects=[]
        for cx, person in zip(top_centers, top_people):
            rect=(cx-card_w//2, top_y, cx+card_w//2, top_y+card_h)
            top_rects.append(rect)
            draw.line((cx, top_y - 28, cx, top_y), fill=line_color, width=3)
            _draw_glass_card(img, rect, person.get('accent_color') or '#1d4c96', person.get('photo_path'), person.get('title') or 'Puesto', person.get('name') or 'Sin nombre', person.get('profession') or '', person.get('email') or '', person.get('phone') or '', director=False)
        if bottom_people:
            bottom_y = top_y + card_h + 120
            if top_rects:
                mid_x = width // 2
                draw.line((mid_x, top_y + card_h, mid_x, bottom_y - 28), fill=line_color, width=3)
            bottom_centers = [width//2 - 220, width//2 + 220][:len(bottom_people)]
            if len(bottom_centers) > 1:
                draw.line((bottom_centers[0], bottom_y - 28, bottom_centers[-1], bottom_y - 28), fill=line_color, width=3)
            for cx, person in zip(bottom_centers, bottom_people):
                rect=(cx-card_w//2, bottom_y, cx+card_w//2, bottom_y+card_h)
                draw.line((cx, bottom_y - 28, cx, bottom_y), fill=line_color, width=3)
                _draw_glass_card(img, rect, person.get('accent_color') or '#d97c2f', person.get('photo_path'), person.get('title') or 'Puesto', person.get('name') or 'Sin nombre', person.get('profession') or '', person.get('email') or '', person.get('phone') or '', director=False)

        footer_font = _load_font(20, False)
        footer_text = 'Base editable para Petroleum · agrega fotos, correos y teléfonos desde administración'
        _text(draw, (width // 2, height - 30), footer_text, footer_font, (175, 194, 222, 220), anchor='mm')
        return img.convert('RGB')

    def _export_petroleum_chart_png(chart: dict[str, Any], petro: dict[str, Any]) -> io.BytesIO:
        poster = _render_petroleum_orgchart_image(chart, petro)
        bio = io.BytesIO()
        poster.save(bio, format='PNG', optimize=True)
        bio.seek(0)
        return bio

    def _export_petroleum_chart_pdf(chart: dict[str, Any], petro: dict[str, Any]) -> io.BytesIO:
        poster = _render_petroleum_orgchart_image(chart, petro)
        return _poster_to_pdf(poster)

    @app.get('/admin/organigrama')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart():
        brand = get_brand()
        if brand == 'consulting':
            chart = _seed_consulting_chart_if_missing()
        else:
            chart = _seed_petroleum_chart_if_missing()
        nodes = _fetch_nodes(int(chart['id'])) if chart and chart.get('id') else []
        departments = [n for n in nodes if n.get('node_type') == 'department']
        persons = [n for n in nodes if n.get('node_type') == 'person']
        nodes.sort(key=lambda n: ((n.get('node_type') != 'department'), int(n.get('parent_id') or 0), int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        persons.sort(key=lambda n: (int(n.get('sort_order') or 0), int(n.get('id') or 0)))
        return render_template(
            'admin/orgchart_manage.html',
            brand=brand,
            chart=chart,
            nodes=nodes,
            departments=departments,
            persons=persons,
            can_create=(brand == 'petroleum' and not chart),
        )

    @app.post('/admin/organigrama/create-base')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart_create_base():
        brand = get_brand()
        if brand == 'consulting':
            _seed_consulting_chart_if_missing()
        else:
            _create_petroleum_base_chart()
        return redirect('/admin/organigrama?created=1')

    @app.post('/admin/organigrama/meta')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart_meta():
        brand = get_brand()
        chart = _fetch_chart(brand)
        if not chart:
            if brand == 'petroleum':
                chart = _create_petroleum_base_chart()
            else:
                chart = _seed_consulting_chart_if_missing()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "UPDATE org_charts SET title=?, subtitle=?, style_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                (request.form.get('title') or '').strip() or chart.get('title') or 'Organigrama',
                (request.form.get('subtitle') or '').strip(),
                (request.form.get('style_name') or 'glass').strip() or 'glass',
                int(chart['id']),
            ),
        )
        conn.commit(); conn.close()
        return redirect('/admin/organigrama?saved=1')

    @app.post('/admin/organigrama/node/save')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart_node_save():
        brand = get_brand()
        chart = _fetch_chart(brand)
        if not chart:
            chart = _create_petroleum_base_chart() if brand == 'petroleum' else _seed_consulting_chart_if_missing()
        node_id = request.form.get('node_id')
        parent_id_raw = request.form.get('parent_id') or None
        parent_id = int(parent_id_raw) if parent_id_raw and parent_id_raw.isdigit() else None
        node_type = (request.form.get('node_type') or 'person').strip().lower()
        if node_type not in {'person', 'department'}:
            node_type = 'person'
        payload = {
            'name': (request.form.get('name') or '').strip() or ('Nueva área' if node_type == 'department' else 'Nuevo integrante'),
            'title': (request.form.get('title') or '').strip(),
            'profession': (request.form.get('profession') or '').strip(),
            'email': (request.form.get('email') or '').strip(),
            'phone': (request.form.get('phone') or '').strip(),
            'accent_color': (request.form.get('accent_color') or '').strip() or ('#1f6feb' if brand == 'consulting' else '#d69b3f'),
            'sort_order': int((request.form.get('sort_order') or '0').strip() or '0'),
            'is_visible': 1 if request.form.get('is_visible') in {'1', 'on', 'true', 'yes'} else 0,
        }
        conn = get_conn(); cur = conn.cursor()
        if node_id and str(node_id).isdigit():
            cur.execute(
                """
                UPDATE org_chart_nodes SET parent_id=?, node_type=?, name=?, title=?, profession=?, email=?, phone=?, accent_color=?, sort_order=?, is_visible=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND chart_id=?
                """,
                (parent_id, node_type, payload['name'], payload['title'], payload['profession'], payload['email'], payload['phone'], payload['accent_color'], payload['sort_order'], payload['is_visible'], int(node_id), int(chart['id'])),
            )
            target_id = int(node_id)
        else:
            cur.execute(
                """
                INSERT INTO org_chart_nodes (chart_id, parent_id, node_type, name, title, profession, email, phone, accent_color, sort_order, is_visible, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                """,
                (int(chart['id']), parent_id, node_type, payload['name'], payload['title'], payload['profession'], payload['email'], payload['phone'], payload['accent_color'], payload['sort_order'], payload['is_visible']),
            )
            target_id = int(cur.lastrowid)
        photo_path = _save_photo(request.files.get('photo'), brand, target_id)
        if photo_path:
            cur.execute("UPDATE org_chart_nodes SET photo_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (photo_path, target_id))
        conn.commit(); conn.close()
        return redirect('/admin/organigrama?saved=1')

    @app.post('/admin/organigrama/node/<int:node_id>/delete')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart_node_delete(node_id: int):
        brand = get_brand()
        chart = _fetch_chart(brand)
        if not chart:
            return redirect('/admin/organigrama')
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, node_type FROM org_chart_nodes WHERE id=? AND chart_id=?", (int(node_id), int(chart['id'])))
        row = cur.fetchone()
        if row:
            if row['node_type'] == 'department':
                cur.execute("DELETE FROM org_chart_nodes WHERE parent_id=? AND chart_id=?", (int(node_id), int(chart['id'])))
            cur.execute("DELETE FROM org_chart_nodes WHERE id=? AND chart_id=?", (int(node_id), int(chart['id'])))
            conn.commit()
        conn.close()
        return redirect('/admin/organigrama?deleted=1')

    @app.post('/admin/organigrama/node/<int:node_id>/move/<direction>')
    @page_login_required
    @page_role_required('admin')
    def admin_orgchart_node_move(node_id: int, direction: str):
        brand = get_brand()
        chart = _fetch_chart(brand)
        if not chart:
            return redirect('/admin/organigrama')
        if direction not in {'up', 'down'}:
            return redirect('/admin/organigrama')
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, parent_id, sort_order FROM org_chart_nodes WHERE id=? AND chart_id=?", (int(node_id), int(chart['id'])))
        current = cur.fetchone()
        if not current:
            conn.close()
            return redirect('/admin/organigrama')
        cur.execute(
            "SELECT id, sort_order FROM org_chart_nodes WHERE chart_id=? AND COALESCE(parent_id,0)=COALESCE(?,0) ORDER BY sort_order ASC, id ASC",
            (int(chart['id']), current['parent_id']),
        )
        siblings = cur.fetchall()
        ids = [int(s['id']) for s in siblings]
        if int(node_id) in ids:
            idx = ids.index(int(node_id))
            swap_idx = idx - 1 if direction == 'up' else idx + 1
            if 0 <= swap_idx < len(siblings):
                other = siblings[swap_idx]
                cur.execute("UPDATE org_chart_nodes SET sort_order=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(other['sort_order']), int(current['id'])))
                cur.execute("UPDATE org_chart_nodes SET sort_order=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(current['sort_order']), int(other['id'])))
                conn.commit()
        conn.close()
        return redirect('/admin/organigrama?sorted=1')

    @app.get('/mod/organigrama')
    @page_login_required
    @page_require_brand
    def view_orgchart():
        me = ctx.get_me() or {}
        brand = get_brand()
        if brand == 'consulting':
            chart, nodes, director, departments = _chart_bundle('consulting')
            return render_template('orgchart/view.html', brand=brand, chart=chart, nodes=nodes, director=director, departments=departments, can_edit=(me.get('role') == 'admin'))
        chart = _seed_petroleum_chart_if_missing()
        nodes = _fetch_nodes(int(chart['id'])) if chart and chart.get('id') else []
        petro = _petroleum_layout(chart, nodes)
        return render_template('orgchart/view.html', brand=brand, chart=chart, nodes=nodes, director=None, departments=[], petro=petro, can_edit=(me.get('role') == 'admin'))

    @app.get('/mod/organigrama/export/<fmt>')
    @page_login_required
    @page_require_brand
    def export_orgchart(fmt: str):
        fmt = (fmt or '').strip().lower()
        if fmt not in {'png', 'pdf'}:
            abort(404)
        brand = get_brand()
        chart, nodes, director, departments = _chart_bundle(brand)
        if not chart:
            abort(404)
        filename_root = secure_filename((chart.get('title') or f'organigrama-{brand}').replace(' ', '-').lower()) or f'organigrama-{brand}'
        inline = request.args.get('inline') in {'1', 'true', 'yes'}
        if brand == 'petroleum':
            petro = _petroleum_layout(chart, nodes)
            if fmt == 'png':
                data = _export_petroleum_chart_png(chart, petro)
                return send_file(data, mimetype='image/png', as_attachment=not inline, download_name=f'{filename_root}.png')
            data = _export_petroleum_chart_pdf(chart, petro)
            return send_file(data, mimetype='application/pdf', as_attachment=not inline, download_name=f'{filename_root}.pdf')
        if not director:
            abort(404)
        if fmt == 'png':
            data = _export_chart_png(brand, chart, director, departments)
            return send_file(data, mimetype='image/png', as_attachment=not inline, download_name=f'{filename_root}.png')
        data = _export_chart_pdf(brand, chart, director, departments)
        return send_file(data, mimetype='application/pdf', as_attachment=not inline, download_name=f'{filename_root}.pdf')

    @app.get('/mod/organigrama/print')
    @page_login_required
    @page_require_brand
    def print_orgchart():
        brand = get_brand()
        chart, nodes, director, departments = _chart_bundle(brand)
        if not chart:
            abort(404)
        return render_template('orgchart/print_image.html', brand=brand, chart=chart)

    @app.get('/consulting/organigrama')
    @page_login_required
    def view_consulting_orgchart_alias():
        me = ctx.get_me() or {}
        if me.get('role') != 'admin' and not user_allows_brand(me, 'consulting'):
            abort(403)
        set_brand('consulting')
        return redirect('/mod/organigrama')

    @app.get('/petroleum/organigrama')
    @page_login_required
    def view_petroleum_orgchart_alias():
        me = ctx.get_me() or {}
        if me.get('role') != 'admin' and not user_allows_brand(me, 'petroleum'):
            abort(403)
        set_brand('petroleum')
        return redirect('/mod/organigrama')

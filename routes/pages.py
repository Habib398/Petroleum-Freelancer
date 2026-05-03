from __future__ import annotations
import os
import re
import json, datetime
from html import escape as html_escape
from io import BytesIO
from flask import request, jsonify, session, redirect, render_template, send_from_directory, abort, current_app, send_file
from werkzeug.security import generate_password_hash
from db import get_conn, verify_user, get_user
from routes.auth import login_required, role_required
from services.outbound import send_email_delivery
from itsdangerous import BadSignature, URLSafeSerializer


def register(app):
    ctx = app.extensions['ctx']

    quote_email_rx = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    quote_recipients = [item.strip() for item in (os.environ.get('PUBLIC_QUOTE_RECIPIENTS') or 'usiel54@hotmail.com,misaelsainz9@gmail.com').split(',') if item.strip()]

    def _quote_serializer() -> URLSafeSerializer:
        secret = (current_app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') or 'worklog-public-quote').strip()
        return URLSafeSerializer(secret, salt='public-quote-pdf')

    def _quote_folio(quote_id: int | None, created_at: str | None = None) -> str:
        date_part = datetime.datetime.now().strftime('%Y%m%d')
        if created_at:
            try:
                parsed = datetime.datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                date_part = parsed.strftime('%Y%m%d')
            except Exception:
                pass
        seq = f"{int(quote_id or 0):05d}"
        return f"COT-{date_part}-{seq}"

    def _read_public_quote(quote_id: int):
        conn = None
        try:
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                """
                SELECT id, full_name, company, phone, contact_email, service_interest, details, created_at
                FROM public_quote_requests
                WHERE id=?
                """,
                (quote_id,),
            )
            row = cur.fetchone()
            conn.close()
            return row
        except Exception:
            try:
                if conn: conn.close()
            except Exception:
                pass
            return None

    def _quote_commercial_profile(service_name: str) -> dict:
        name = (service_name or '').strip().lower()
        profile = {
            'estimate_range': 'Propuesta económica sujeta a revisión técnica del alcance.',
            'timeline': 'Presentación de propuesta formal en 2 a 5 días hábiles.',
            'validity_days': 15,
            'deliverables': [
                'Resumen ejecutivo del requerimiento y canal de atención.',
                'Revisión preliminar de alcance, riesgo operativo y documentos base.',
                'Propuesta formal con costo definitivo, tiempos y condiciones finales.',
            ],
        }
        if 'consult' in name or 'cumpl' in name:
            profile.update({
                'estimate_range': '$18,000 a $45,000 MXN + IVA (referencia preliminar).',
                'timeline': 'Propuesta formal en 2 a 4 días hábiles.',
            })
        elif 'inspe' in name or 'norma' in name:
            profile.update({
                'estimate_range': '$22,000 a $60,000 MXN + IVA (según estación, visita y expediente).',
                'timeline': 'Propuesta formal en 2 a 5 días hábiles.',
            })
        elif 'document' in name:
            profile.update({
                'estimate_range': '$12,000 a $28,000 MXN + IVA (según volumen documental).',
                'timeline': 'Propuesta formal en 1 a 3 días hábiles.',
            })
        elif 'work log' in name or 'corporativo' in name or 'plataforma' in name:
            profile.update({
                'estimate_range': '$35,000 a $120,000 MXN + IVA (según módulos, estaciones y despliegue).',
                'timeline': 'Propuesta formal en 3 a 7 días hábiles.',
            })
        elif 'otro' in name:
            profile.update({
                'estimate_range': 'Monto a definir tras llamada y levantamiento de requerimientos.',
                'timeline': 'Tiempo de propuesta sujeto a la complejidad del caso.',
            })
        return profile

    def _build_quote_pdf(quote_row) -> bytes:
        from pathlib import Path
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfgen import canvas

        def val(key, default='-'):
            if quote_row is None:
                return default
            try:
                if isinstance(quote_row, dict):
                    got = quote_row.get(key, default)
                else:
                    got = quote_row[key]
            except Exception:
                got = default
            return got or default

        def wrap_lines(text_value: str, max_width: float, font_name: str = 'Helvetica', font_size: float = 10.0):
            text_value = str(text_value or '-').replace('\r', '').strip() or '-'
            paragraphs = [part.strip() for part in text_value.split('\n')] or ['-']
            lines: list[str] = []
            for para in paragraphs:
                words = para.split() or ['-']
                current = ''
                for word in words:
                    test = (current + ' ' + word).strip()
                    if current and stringWidth(test, font_name, font_size) > max_width:
                        lines.append(current)
                        current = word
                    else:
                        current = test
                if current:
                    lines.append(current)
                lines.append('')
            while lines and lines[-1] == '':
                lines.pop()
            return lines or ['-']

        def draw_logo(cnv, img_path: Path, x: float, y: float, w: float, h: float):
            if not img_path.exists():
                return
            try:
                cnv.drawImage(ImageReader(str(img_path)), x, y, width=w, height=h, preserveAspectRatio=True, mask='auto')
            except Exception:
                return

        def draw_footer(cnv, page_num: int, folio: str, width: float, margin: float):
            cnv.setStrokeColor(colors.HexColor('#d6deea'))
            cnv.line(margin, 0.72 * inch, width - margin, 0.72 * inch)
            cnv.setFillColor(colors.HexColor('#5f6f86'))
            cnv.setFont('Helvetica', 8.8)
            cnv.drawString(margin, 0.52 * inch, 'Documento generado automáticamente por Work Log Corporativo.')
            cnv.drawRightString(width - margin, 0.52 * inch, f'{folio} · Página {page_num}')

        def draw_wrapped_block(cnv, x: float, y: float, label: str, value: str, width_limit: float, label_color, value_color, font_size: float = 10.1):
            cnv.setFillColor(label_color)
            cnv.setFont('Helvetica-Bold', 9.2)
            cnv.drawString(x, y, label.upper())
            cnv.setFillColor(value_color)
            cnv.setFont('Helvetica', font_size)
            lines = wrap_lines(value, width_limit, 'Helvetica', font_size)
            current_y = y - 16
            for line in lines:
                cnv.drawString(x, current_y, line or ' ')
                current_y -= 12
            return current_y

        def draw_bullets(cnv, x: float, y: float, items: list[str], width_limit: float, bullet_color, text_color, font_size: float = 9.6, leading: float = 13.0):
            current_y = y
            cnv.setFont('Helvetica', font_size)
            for item in items:
                lines = wrap_lines(item, width_limit - 12, 'Helvetica', font_size)
                first = True
                for line in lines:
                    if first:
                        cnv.setFillColor(bullet_color)
                        cnv.drawString(x, current_y, '•')
                        cnv.setFillColor(text_color)
                        cnv.drawString(x + 12, current_y, line)
                        first = False
                    else:
                        cnv.setFillColor(text_color)
                        cnv.drawString(x + 12, current_y, line)
                    current_y -= leading
                current_y -= 3
            return current_y

        created_raw = val('created_at', '')
        created_dt = datetime.datetime.now()
        if created_raw:
            try:
                created_dt = datetime.datetime.fromisoformat(str(created_raw).replace('Z', '+00:00'))
            except Exception:
                pass
        created_label = created_dt.strftime('%d/%m/%Y %H:%M')
        folio = _quote_folio(val('id', 0), created_raw)
        service_name = str(val('service_interest'))
        commercial = _quote_commercial_profile(service_name)
        estimate_range = commercial['estimate_range']
        timeline = commercial['timeline']
        validity_days = int(commercial['validity_days'])
        validity_until = (created_dt + datetime.timedelta(days=validity_days)).strftime('%d/%m/%Y')
        detail_lines = wrap_lines(val('details'), 6.40 * inch, 'Helvetica', 10.0)
        deliverables = commercial['deliverables']
        commercial_conditions = [
            'El monto mostrado es únicamente un rango preliminar y puede cambiar según alcance definitivo, número de estaciones, visitas, urgencia y documentación disponible.',
            'La propuesta económica final se emite después de validación técnica y comercial del caso.',
            'Tiempos, viáticos, entregables y forma de pago se confirman en la propuesta formal o contrato correspondiente.',
            'La presente hoja funciona como acuse y resumen ejecutivo de la solicitud recibida desde el portal público.',
        ]
        principal_phone = os.environ.get('PUBLIC_CONTACT_PRIMARY_PHONE') or '771-379-5843'
        principal_email = os.environ.get('PUBLIC_CONTACT_PRIMARY_EMAIL') or 'usiel54@hotmail.com'
        secondary_email = os.environ.get('PUBLIC_CONTACT_SECONDARY_EMAIL') or 'misaelsainz9@gmail.com'
        commercial_name = os.environ.get('PUBLIC_QUOTE_SIGNER_NAME') or 'Atención Comercial Corporativa'
        commercial_title = os.environ.get('PUBLIC_QUOTE_SIGNER_TITLE') or 'Consulting Oil & Gas · Petroleum IU'
        whatsapp_url = os.environ.get('PUBLIC_CONTACT_PRIMARY_WHATSAPP') or 'https://wa.me/527713795843'

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        margin = 0.60 * inch

        navy = colors.HexColor('#0b1f3a')
        navy_2 = colors.HexColor('#0f3156')
        green = colors.HexColor('#1d8f6e')
        green_dark = colors.HexColor('#136c55')
        gold = colors.HexColor('#c8922e')
        gold_soft = colors.HexColor('#f5e7c5')
        text = colors.HexColor('#172033')
        muted = colors.HexColor('#5f6f86')
        border = colors.HexColor('#d8e1ec')
        soft = colors.HexColor('#f5f8fc')
        soft_2 = colors.HexColor('#eef3f9')
        white = colors.white

        base_dir = Path(current_app.root_path)
        consulting_logo = base_dir / 'static' / 'img' / 'consulting-logo-full.png'
        petroleum_logo = base_dir / 'static' / 'img' / 'petroleum-logo-full.png'

        c.setAuthor('Work Log Corporativo')
        c.setSubject(f'Solicitud de cotización {folio}')
        c.setTitle(f'Solicitud de cotización {folio}')

        # Página 1
        c.setFillColor(soft)
        c.rect(0, 0, width, height, fill=1, stroke=0)
        c.setFillColor(navy)
        c.rect(0, height - 2.14 * inch, width, 2.14 * inch, fill=1, stroke=0)
        c.setFillColor(navy_2)
        c.rect(0, height - 2.38 * inch, width, 0.24 * inch, fill=1, stroke=0)

        draw_logo(c, consulting_logo, margin, height - 1.02 * inch, 1.78 * inch, 0.62 * inch)
        draw_logo(c, petroleum_logo, width - margin - 1.56 * inch, height - 1.02 * inch, 1.46 * inch, 0.56 * inch)

        chip_w = stringWidth(folio, 'Helvetica-Bold', 10.8) + 30
        chip_x = width - margin - chip_w
        chip_y = height - 1.57 * inch
        c.setFillColor(green)
        c.roundRect(chip_x, chip_y, chip_w, 0.34 * inch, 11, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 10.8)
        c.drawCentredString(chip_x + chip_w / 2, chip_y + 0.115 * inch, folio)

        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 22)
        c.drawString(margin, height - 1.40 * inch, 'Solicitud de cotización corporativa')
        c.setFont('Helvetica', 11)
        c.drawString(margin, height - 1.68 * inch, 'Resumen ejecutivo preliminar para atención comercial y propuesta formal')

        c.setFillColor(white)
        c.setStrokeColor(colors.Color(1, 1, 1, .18))
        c.roundRect(margin, height - 2.98 * inch, width - 2 * margin, 0.58 * inch, 18, fill=0, stroke=1)
        c.setFont('Helvetica-Bold', 11)
        c.drawString(margin + 16, height - 2.65 * inch, f'Servicio solicitado: {service_name}')

        body_top = height - 3.28 * inch
        left_w = 3.00 * inch
        right_x = margin + left_w + 0.20 * inch
        right_w = width - right_x - margin

        c.setFillColor(white)
        c.setStrokeColor(border)
        c.roundRect(margin, 1.18 * inch, left_w, body_top - 1.18 * inch, 20, fill=1, stroke=1)
        c.roundRect(right_x, 2.88 * inch, right_w, body_top - 2.88 * inch, 20, fill=1, stroke=1)
        c.roundRect(right_x, 1.18 * inch, right_w, 1.38 * inch, 20, fill=1, stroke=1)

        c.setFillColor(green_dark)
        c.roundRect(margin + 16, body_top - 22, 1.52 * inch, 0.28 * inch, 9, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 8.7)
        c.drawCentredString(margin + 16 + 0.76 * inch, body_top - 13.7, 'DATOS DEL SOLICITANTE')

        c.setFillColor(gold)
        c.roundRect(right_x + 16, body_top - 22, 1.70 * inch, 0.28 * inch, 9, fill=1, stroke=0)
        c.setFillColor(white)
        c.drawCentredString(right_x + 16 + 0.85 * inch, body_top - 13.7, 'RESUMEN COMERCIAL')

        y_left = body_top - 46
        y_left = draw_wrapped_block(c, margin + 18, y_left, 'Cliente', val('full_name'), left_w - 40, text, text)
        y_left -= 6
        y_left = draw_wrapped_block(c, margin + 18, y_left, 'Empresa', val('company'), left_w - 40, text, text)
        y_left -= 6
        y_left = draw_wrapped_block(c, margin + 18, y_left, 'Teléfono', val('phone'), left_w - 40, text, text)
        y_left -= 6
        y_left = draw_wrapped_block(c, margin + 18, y_left, 'Correo', val('contact_email'), left_w - 40, text, text)

        c.setFillColor(soft)
        c.roundRect(margin + 16, 1.48 * inch, left_w - 32, 1.48 * inch, 16, fill=1, stroke=0)
        c.setFillColor(text)
        c.setFont('Helvetica-Bold', 10.4)
        c.drawString(margin + 28, 2.64 * inch, 'Canal de seguimiento')
        c.setFillColor(muted)
        c.setFont('Helvetica', 9.5)
        followup = [
            f'• Folio de seguimiento: {folio}',
            f'• Línea principal: {principal_phone}',
            f'• Correo principal: {principal_email}',
            '• El caso entra a revisión comercial y técnica inicial.',
        ]
        for idx, line in enumerate(followup):
            c.drawString(margin + 28, 2.36 * inch - (idx * 0.18 * inch), line)

        c.setFillColor(text)
        c.setFont('Helvetica-Bold', 17)
        c.drawString(right_x + 18, body_top - 48, service_name)
        c.setFillColor(muted)
        c.setFont('Helvetica', 10.0)
        c.drawString(right_x + 18, body_top - 67, f'Fecha de recepción: {created_label}')
        c.drawString(right_x + 18, body_top - 82, 'Estatus inicial: solicitud recibida y en integración de propuesta.')

        top_metrics_y = body_top - 132
        box_w = (right_w - 54) / 3
        metrics = [
            ('Monto estimado', estimate_range),
            ('Tiempo de respuesta', timeline),
            ('Vigencia preliminar', f'{validity_days} días · hasta {validity_until}'),
        ]
        for idx, (label, value) in enumerate(metrics):
            box_x = right_x + 18 + idx * (box_w + 9)
            c.setFillColor(soft)
            c.roundRect(box_x, top_metrics_y, box_w, 0.82 * inch, 15, fill=1, stroke=0)
            c.setFillColor(navy)
            c.setFont('Helvetica-Bold', 9.0)
            c.drawString(box_x + 12, top_metrics_y + 0.53 * inch, label)
            c.setFillColor(text)
            c.setFont('Helvetica', 9.1)
            lines = wrap_lines(value, box_w - 24, 'Helvetica', 9.1)[:3]
            for line_idx, line in enumerate(lines):
                c.drawString(box_x + 12, top_metrics_y + 0.33 * inch - (line_idx * 11), line)

        c.setFillColor(text)
        c.setFont('Helvetica-Bold', 11.4)
        c.drawString(right_x + 18, body_top - 190, 'Detalle capturado por el cliente')
        c.setFillColor(muted)
        c.setFont('Helvetica', 9.3)
        c.drawString(right_x + 18, body_top - 205, 'Texto registrado desde la página pública para generar seguimiento comercial.')

        max_first_page = 17
        detail_y = body_top - 228
        c.setFillColor(text)
        c.setFont('Helvetica', 10.0)
        remaining_lines = []
        for idx, line in enumerate(detail_lines):
            if idx >= max_first_page:
                remaining_lines = detail_lines[idx:]
                break
            c.drawString(right_x + 18, detail_y - (idx * 13.5), line or ' ')

        c.setFillColor(gold_soft)
        c.roundRect(right_x + 18, 1.46 * inch, right_w - 36, 0.98 * inch, 16, fill=1, stroke=0)
        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10.5)
        c.drawString(right_x + 30, 2.14 * inch, 'Entregables preliminares')
        c.setFillColor(text)
        c.setFont('Helvetica', 9.6)
        for idx, item in enumerate(deliverables[:3]):
            c.drawString(right_x + 30, 1.93 * inch - (idx * 0.18 * inch), f'{idx + 1}. {item}')
        c.setFillColor(muted)
        c.setFont('Helvetica', 8.8)
        c.drawRightString(right_x + right_w - 18, 1.54 * inch, 'Resumen preliminar sujeto a validación final')

        draw_footer(c, 1, folio, width, margin)

        # Página 2: condiciones y firma, con o sin continuación
        c.showPage()
        c.setFillColor(soft)
        c.rect(0, 0, width, height, fill=1, stroke=0)
        c.setFillColor(navy)
        c.rect(0, height - 0.94 * inch, width, 0.94 * inch, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 15)
        c.drawString(margin, height - 0.58 * inch, f'{folio} · Propuesta preliminar y condiciones')
        c.setFont('Helvetica', 9.6)
        c.drawRightString(width - margin, height - 0.58 * inch, 'Work Log Corporativo')

        c.setFillColor(white)
        c.setStrokeColor(border)
        c.roundRect(margin, 1.18 * inch, width - 2 * margin, height - 2.38 * inch, 18, fill=1, stroke=1)

        c.setFillColor(text)
        c.setFont('Helvetica-Bold', 11.2)
        c.drawString(margin + 18, height - 1.34 * inch, 'Detalle del requerimiento')
        c.setFillColor(muted)
        c.setFont('Helvetica', 9.2)
        c.drawString(margin + 18, height - 1.54 * inch, 'Continuación y soporte comercial preliminar de la solicitud capturada.')

        detail_start_y = height - 1.84 * inch
        detail_limit_bottom = 4.98 * inch
        c.setFillColor(text)
        c.setFont('Helvetica', 10.0)
        lines_to_render = remaining_lines or ['Sin texto adicional. El detalle quedó contenido en la primera página.']
        current_y = detail_start_y
        overflow_lines: list[str] = []
        for idx, line in enumerate(lines_to_render):
            if current_y < detail_limit_bottom:
                overflow_lines = lines_to_render[idx:]
                break
            c.drawString(margin + 18, current_y, line or ' ')
            current_y -= 13.3

        lower_box_y = 1.42 * inch
        lower_box_h = 3.20 * inch
        left_box_w = 3.75 * inch
        right_box_x = margin + left_box_w + 0.18 * inch
        right_box_w = width - margin - right_box_x

        c.setFillColor(soft)
        c.roundRect(margin + 18, lower_box_y, left_box_w, lower_box_h, 16, fill=1, stroke=0)
        c.setFillColor(soft_2)
        c.roundRect(right_box_x, lower_box_y, right_box_w, lower_box_h, 16, fill=1, stroke=0)

        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10.6)
        c.drawString(margin + 30, lower_box_y + lower_box_h - 22, 'Condiciones comerciales preliminares')
        draw_bullets(c, margin + 30, lower_box_y + lower_box_h - 42, commercial_conditions, left_box_w - 26, green_dark, text, 9.4, 12.8)

        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10.6)
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 22, 'Firma y datos de atención')
        c.setFillColor(text)
        c.setFont('Helvetica-Bold', 12.0)
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 50, commercial_name)
        c.setFillColor(muted)
        c.setFont('Helvetica', 9.8)
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 66, commercial_title)
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 82, f'Correo: {principal_email}')
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 97, f'Respaldo: {secondary_email}')
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 112, f'Teléfono / WhatsApp: {principal_phone}')
        c.drawString(right_box_x + 16, lower_box_y + lower_box_h - 127, f'Canal rápido: {whatsapp_url.replace("https://", "") }')

        c.setStrokeColor(colors.HexColor('#9bb3cc'))
        c.line(right_box_x + 16, lower_box_y + 0.86 * inch, right_box_x + right_box_w - 18, lower_box_y + 0.86 * inch)
        c.setFillColor(muted)
        c.setFont('Helvetica', 9.0)
        c.drawString(right_box_x + 16, lower_box_y + 0.64 * inch, 'Firma / Vo. Bo. área comercial')
        c.drawString(right_box_x + 16, lower_box_y + 0.42 * inch, f'Vigencia preliminar del documento: hasta {validity_until}')

        draw_footer(c, 2, folio, width, margin)

        page_num = 3
        while overflow_lines:
            c.showPage()
            c.setFillColor(soft)
            c.rect(0, 0, width, height, fill=1, stroke=0)
            c.setFillColor(navy)
            c.rect(0, height - 0.92 * inch, width, 0.92 * inch, fill=1, stroke=0)
            c.setFillColor(white)
            c.setFont('Helvetica-Bold', 15)
            c.drawString(margin, height - 0.57 * inch, f'{folio} · Continuación del detalle')
            c.setFont('Helvetica', 9.8)
            c.drawRightString(width - margin, height - 0.57 * inch, 'Work Log Corporativo')

            c.setFillColor(white)
            c.setStrokeColor(border)
            c.roundRect(margin, 1.18 * inch, width - 2 * margin, height - 2.42 * inch, 18, fill=1, stroke=1)
            c.setFillColor(text)
            c.setFont('Helvetica-Bold', 11.2)
            c.drawString(margin + 18, height - 1.34 * inch, 'Continuación del requerimiento capturado')
            c.setFillColor(muted)
            c.setFont('Helvetica', 9.2)
            c.drawString(margin + 18, height - 1.54 * inch, 'Texto adicional generado automáticamente cuando el detalle supera dos páginas.')

            c.setFillColor(text)
            c.setFont('Helvetica', 10.0)
            start_y = height - 1.86 * inch
            lines_per_page = 41
            chunk = overflow_lines[:lines_per_page]
            overflow_lines = overflow_lines[lines_per_page:]
            for idx, line in enumerate(chunk):
                c.drawString(margin + 18, start_y - (idx * 13.5), line or ' ')

            c.setFillColor(soft_2)
            c.roundRect(margin, 0.90 * inch, width - 2 * margin, 0.42 * inch, 12, fill=1, stroke=0)
            c.setFillColor(muted)
            c.setFont('Helvetica', 8.8)
            c.drawString(margin + 14, 1.05 * inch, 'Esta continuación forma parte del mismo folio de seguimiento y soporte comercial preliminar.')
            draw_footer(c, page_num, folio, width, margin)
            page_num += 1

        c.save()
        return buffer.getvalue()

    def _send_quote_email(payload: dict, *, pdf_bytes: bytes | None = None, pdf_filename: str | None = None, folio: str | None = None) -> tuple[bool, str]:
        service_label = (payload.get('service_interest') or 'General').strip() or 'General'
        folio_label = (folio or '-').strip() or '-'
        full_name = (payload.get('full_name') or '-').strip() or '-'
        company = (payload.get('company') or '-').strip() or '-'
        phone = (payload.get('phone') or '-').strip() or '-'
        contact_email = (payload.get('contact_email') or '-').strip() or '-'
        details = (payload.get('details') or '-').strip() or '-'
        created_label = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')

        body = [
            'Se recibió una nueva solicitud de cotización desde la página pública.',
            '',
            f"Folio: {folio_label}",
            f"Fecha: {created_label}",
            f"Nombre: {full_name}",
            f"Empresa: {company}",
            f"Teléfono: {phone}",
            f"Correo de contacto: {contact_email}",
            f"Servicio de interés: {service_label}",
            '',
            'Detalles:',
            details,
            '',
            'Se adjunta el PDF generado de la solicitud para seguimiento comercial.',
        ]

        html_body = f"""
<!doctype html>
<html lang="es">
  <body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#16324f;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Nueva cotización recibida con folio {html_escape(folio_label)}.</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #d9e4f1;">
            <tr>
              <td style="background:linear-gradient(135deg,#0f2740 0%,#163b63 100%);padding:28px 32px;color:#ffffff;">
                <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:.82;">Work Log · Nueva cotización</div>
                <div style="font-size:26px;line-height:1.2;font-weight:700;margin-top:8px;">{html_escape(folio_label)}</div>
                <div style="font-size:14px;line-height:1.6;opacity:.92;margin-top:8px;">Solicitud recibida desde la página pública para seguimiento comercial interno.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 32px 16px 32px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="padding:0 0 20px 0;">
                      <div style="font-size:13px;color:#5c708a;text-transform:uppercase;letter-spacing:.08em;font-weight:700;">Servicio solicitado</div>
                      <div style="font-size:20px;color:#16324f;font-weight:700;margin-top:6px;">{html_escape(service_label)}</div>
                    </td>
                    <td align="right" style="padding:0 0 20px 0;">
                      <div style="display:inline-block;background:#e8f7ef;color:#0d7a43;border:1px solid #b8e1c9;border-radius:999px;padding:8px 14px;font-size:12px;font-weight:700;">Recepción: {html_escape(created_label)}</div>
                    </td>
                  </tr>
                </table>

                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:separate;border-spacing:0 10px;">
                  <tr>
                    <td width="50%" valign="top" style="padding-right:8px;">
                      <div style="background:#f8fbff;border:1px solid #dbe7f3;border-radius:14px;padding:18px;">
                        <div style="font-size:12px;color:#5c708a;text-transform:uppercase;letter-spacing:.08em;font-weight:700;">Contacto</div>
                        <div style="font-size:16px;font-weight:700;color:#16324f;margin-top:8px;">{html_escape(full_name)}</div>
                        <div style="font-size:14px;color:#40566f;margin-top:8px;"><strong>Empresa:</strong> {html_escape(company)}</div>
                        <div style="font-size:14px;color:#40566f;margin-top:6px;"><strong>Teléfono:</strong> {html_escape(phone)}</div>
                        <div style="font-size:14px;color:#40566f;margin-top:6px;word-break:break-word;"><strong>Correo:</strong> {html_escape(contact_email)}</div>
                      </div>
                    </td>
                    <td width="50%" valign="top" style="padding-left:8px;">
                      <div style="background:#f8fbff;border:1px solid #dbe7f3;border-radius:14px;padding:18px;">
                        <div style="font-size:12px;color:#5c708a;text-transform:uppercase;letter-spacing:.08em;font-weight:700;">Seguimiento interno</div>
                        <div style="font-size:14px;color:#40566f;margin-top:8px;line-height:1.7;">
                          <strong>Acción sugerida:</strong> Revisar alcance, validar documentos base y preparar propuesta comercial formal.
                        </div>
                        <div style="font-size:14px;color:#40566f;margin-top:6px;line-height:1.7;">
                          <strong>Adjunto:</strong> PDF de la solicitud generado automáticamente.
                        </div>
                        <div style="font-size:14px;color:#40566f;margin-top:6px;line-height:1.7;">
                          <strong>Destinatarios:</strong> solo correo principal y secundario internos.
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>

                <div style="margin-top:8px;background:#ffffff;border:1px solid #dbe7f3;border-radius:14px;padding:18px;">
                  <div style="font-size:12px;color:#5c708a;text-transform:uppercase;letter-spacing:.08em;font-weight:700;">Detalle capturado</div>
                  <div style="font-size:14px;line-height:1.75;color:#20364d;white-space:pre-wrap;margin-top:10px;">{html_escape(details)}</div>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 28px 32px;">
                <div style="background:#eef4fb;border-radius:14px;padding:16px 18px;font-size:13px;line-height:1.7;color:#51667f;">
                  Este mensaje fue generado automáticamente por el módulo público de cotizaciones de Work Log.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

        attachments = []
        if pdf_bytes:
            attachments.append({
                'filename': (pdf_filename or f'solicitud_cotizacion_{folio_label.lower()}.pdf').replace(' ', '_'),
                'data': pdf_bytes,
                'mimetype': 'application/pdf',
            })
        subject = f"Nueva cotización recibida · {folio_label} · {service_label}"
        return send_email_delivery(
            quote_recipients,
            subject,
            '\n'.join(body),
            brand='consulting',
            reply_to=payload.get('contact_email') or None,
            attachments=attachments,
            html_body=html_body,
        )

    @app.get("/")
    def root():
        # Landing page (single login button). Brand is selected AFTER login.
        return render_template("inicio.html")

    @app.get("/inicio")
    def inicio():
        return redirect("/")

    @app.get("/login")
    def login_page():
        # Single login for both systems. Brand is selected AFTER login.
        return render_template("login.html")

    def _render_public_legal_page(page_key: str):
        today = datetime.date.today().strftime("%d/%m/%Y")
        pages = {
            "privacy": {
                "title": "Política de Privacidad",
                "intro": "Este aviso explica de forma general cómo se resguarda la información utilizada dentro de la plataforma corporativa de Consulting Oil & Gas y Petroleum IU.",
                "sections": [
                    {
                        "title": "Datos que pueden recabarse",
                        "body": "La plataforma puede almacenar datos de acceso, información de usuarios autorizados, registros de estaciones, documentos cargados, evidencias, bitácoras, notificaciones internas y trazabilidad operativa necesaria para el funcionamiento del sistema."
                    },
                    {
                        "title": "Uso de la información",
                        "body": "La información se utiliza para control documental, seguimiento de cumplimiento, administración de roles, validación de actividades, revisiones internas y operación segura del sistema. No se contempla el uso de los datos con fines ajenos a la operación y gestión empresarial."
                    },
                    {
                        "title": "Resguardo y acceso",
                        "body": "El acceso a la información se limita de acuerdo con los permisos asignados a cada usuario. Los administradores, jefes de estación y operadores únicamente visualizan o gestionan la información permitida según su perfil y su empresa asignada."
                    },
                    {
                        "title": "Actualizaciones",
                        "body": "Este aviso puede ajustarse cuando existan cambios operativos, legales o tecnológicos en la plataforma. La versión pública vigente será la que se encuentre publicada en este portal."
                    }
                ]
            },
            "cookies": {
                "title": "Política de Cookies",
                "intro": "Este documento describe el uso general de cookies o tecnologías equivalentes en la experiencia pública y de acceso del sistema corporativo.",
                "sections": [
                    {
                        "title": "Cookies esenciales",
                        "body": "La plataforma puede utilizar cookies técnicas o de sesión para permitir el inicio de sesión, mantener la autenticación activa y mejorar la seguridad durante la navegación de usuarios autorizados."
                    },
                    {
                        "title": "Uso funcional",
                        "body": "Las cookies funcionales pueden ayudar a recordar preferencias básicas de visualización, mantener flujos de acceso y mejorar la estabilidad de la experiencia de usuario dentro del sistema."
                    },
                    {
                        "title": "Control del navegador",
                        "body": "El usuario puede administrar o desactivar cookies desde la configuración de su navegador. Algunas funciones del sistema pueden verse afectadas si se bloquean elementos esenciales para autenticación o navegación segura."
                    }
                ]
            },
            "terms": {
                "title": "Términos y Condiciones",
                "intro": "Estas condiciones regulan el uso general de la plataforma corporativa de gestión, cumplimiento y control operativo puesta a disposición por Consulting Oil & Gas y Petroleum IU.",
                "sections": [
                    {
                        "title": "Uso autorizado",
                        "body": "El acceso a la plataforma está destinado exclusivamente a usuarios autorizados por la administración del sistema. Cada usuario es responsable del uso correcto de sus credenciales y del resguardo de la información a la que tenga acceso."
                    },
                    {
                        "title": "Disponibilidad y cambios",
                        "body": "La administración puede modificar módulos, contenidos, procesos, nombres de secciones, documentos, flujos operativos o elementos visuales del sistema cuando sea necesario para la operación de la empresa o el cumplimiento normativo."
                    },
                    {
                        "title": "Responsabilidad sobre la información",
                        "body": "Los usuarios deben capturar, revisar y cargar información veraz dentro de los apartados permitidos. La aprobación, validación o actualización documental seguirá las reglas internas configuradas por la empresa y por el administrador del sistema."
                    },
                    {
                        "title": "Propiedad y uso del contenido",
                        "body": "El contenido, estructura, diseños, plantillas, documentos y configuraciones del sistema forman parte de la operación corporativa y no deben copiarse, distribuirse o utilizarse fuera de los fines autorizados por la empresa."
                    }
                ]
            }
        }
        page = pages.get(page_key)
        if not page:
            abort(404)
        return render_template(
            "public_legal.html",
            legal_title=page["title"],
            legal_intro=page["intro"],
            sections=page["sections"],
            updated_at=today,
        )

    @app.get("/privacy-policy")
    def privacy_policy_page():
        return _render_public_legal_page("privacy")

    @app.get("/cookies-policy")
    def cookies_policy_page():
        return _render_public_legal_page("cookies")

    @app.get("/terms-and-conditions")
    def terms_and_conditions_page():
        return _render_public_legal_page("terms")

    @app.post("/api/public/quote-request")
    def api_public_quote_request():
        data = request.form if request.form else (request.get_json(silent=True) or {})
        payload = {
            'full_name': (data.get('full_name') or '').strip(),
            'company': (data.get('company') or '').strip(),
            'phone': (data.get('phone') or '').strip(),
            'contact_email': (data.get('contact_email') or '').strip().lower(),
            'service_interest': (data.get('service_interest') or '').strip(),
            'details': (data.get('details') or '').strip(),
        }

        if not payload['full_name'] or not payload['phone'] or not payload['service_interest'] or not payload['details']:
            return jsonify({'ok': False, 'message': 'Completa nombre, teléfono, servicio de interés y detalles.'}), 400
        if payload['contact_email'] and not quote_email_rx.match(payload['contact_email']):
            return jsonify({'ok': False, 'message': 'El correo de contacto no es válido.'}), 400

        ip_addr = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
        user_agent = (request.headers.get('User-Agent') or '')[:500]

        quote_id = None
        quote_created_at = None
        try:
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO public_quote_requests (
                    full_name, company, phone, contact_email, service_interest, details,
                    source_page, ip_address, user_agent, email_delivery_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                RETURNING id, created_at
                """,
                (
                    payload['full_name'],
                    payload['company'] or None,
                    payload['phone'],
                    payload['contact_email'] or None,
                    payload['service_interest'],
                    payload['details'],
                    'inicio',
                    ip_addr or None,
                    user_agent or None,
                    'stored',
                ),
            )
            inserted = cur.fetchone()
            try:
                quote_id = inserted['id']
                quote_created_at = inserted.get('created_at')
            except Exception:
                try:
                    quote_id = inserted[0]
                    quote_created_at = inserted[1] if len(inserted) > 1 else None
                except Exception:
                    quote_id = getattr(cur, 'lastrowid', None)
            conn.commit(); conn.close()
        except Exception as exc:
            current_app.logger.exception('No se pudo guardar solicitud de cotización: %s', exc)
            try:
                conn.close()
            except Exception:
                pass
            return jsonify({'ok': False, 'message': 'No se pudo registrar la solicitud en este momento.'}), 500

        quote_row = _read_public_quote(quote_id) if quote_id is not None else None
        quote_folio = _quote_folio(quote_id, quote_created_at) if quote_id is not None else None
        pdf_url = None
        pdf_bytes = None
        pdf_filename = None
        if quote_id is not None:
            token = _quote_serializer().dumps({'quote_id': int(quote_id)})
            pdf_url = f"/api/public/quote-request/{token}/pdf"
            try:
                source_row = quote_row or payload
                pdf_bytes = _build_quote_pdf(source_row)
                pdf_filename = f"solicitud_cotizacion_{(quote_folio or str(quote_id)).lower()}.pdf"
            except Exception as exc:
                current_app.logger.exception('No se pudo generar PDF de cotización %s: %s', quote_id, exc)

        email_payload = quote_row or payload
        sent, detail = _send_quote_email(email_payload, pdf_bytes=pdf_bytes, pdf_filename=pdf_filename, folio=quote_folio)
        status = 'sent' if sent else 'stored'
        if quote_id is not None:
            try:
                conn = get_conn(); cur = conn.cursor()
                cur.execute(
                    'UPDATE public_quote_requests SET email_delivery_status=?, email_delivery_error=? WHERE id=?',
                    (status, None if sent else detail, quote_id),
                )
                conn.commit(); conn.close()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

        return jsonify({
            'ok': True,
            'status': status,
            'message': 'Solicitud registrada correctamente.' if status == 'stored' else 'Solicitud enviada correctamente.',
            'quote_id': quote_id,
            'folio': quote_folio,
            'pdf_url': pdf_url,
        })

    @app.get('/api/public/quote-request/<token>/pdf')
    def api_public_quote_request_pdf(token: str):
        try:
            data = _quote_serializer().loads(token)
            quote_id = int(data.get('quote_id'))
        except (BadSignature, ValueError, TypeError):
            abort(404)

        row = _read_public_quote(quote_id)
        if not row:
            abort(404)

        created_at = None
        try:
            created_at = row.get('created_at')
        except Exception:
            try:
                created_at = row['created_at']
            except Exception:
                created_at = None

        pdf_bytes = _build_quote_pdf(row)
        filename = f"solicitud_cotizacion_{_quote_folio(quote_id, created_at).lower()}.pdf"
        download = str(request.args.get('download') or '').strip().lower() in {'1', 'true', 'yes'}
        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=download,
            download_name=filename,
            max_age=0,
        )

    @app.get("/admin/menu")
    @login_required
    @role_required("admin")
    def admin_menu():
        from services.brand import get_brand
        return render_template("admin_menu.html", brand=get_brand())
    @app.get("/select-system")
    @login_required
    @role_required("admin","auditor","contador","jefe_estacion","operador")
    def select_system():
        """
        Selector de empresa (Consulting / Petroleum) DESPUÉS del login.
        - Admin: siempre ve ambas opciones.
        - Otros roles: si solo tienen una empresa asignada, se auto-selecciona.
        """
        from services.brand import parse_allowed_brands, set_brand

        me = ctx.get_me() or {}
        role = (me.get("role") or "").strip().lower()

        if role == "admin":
            allowed = {"consulting", "petroleum"}
        else:
            allowed = parse_allowed_brands(me.get("allowed_brands"))

        if len(allowed) == 1:
            chosen = next(iter(allowed))
            set_brand(chosen)
            # Post-login landing:
            # - Admin -> módulo hub according to active brand
            # - Others -> shared dashboard
            if role == "admin":
                return redirect("/admin/menu")
            return redirect("/staff/menu")

        return render_template("select_system.html", allowed=sorted(list(allowed)))



    @app.post("/api/set-brand")
    @login_required
    def api_set_brand():
        from services.brand import set_brand, parse_allowed_brands, VALID_BRANDS
        data = request.get_json(silent=True) or {}
        brand = (data.get("brand") or "").strip().lower()

        me = ctx.get_me() or {}
        role = (me.get("role") or "").strip().lower()

        if brand not in VALID_BRANDS:
            return jsonify({"ok": False, "error": "invalid_brand"}), 400

        if role == "admin":
            set_brand(brand)
            redirect_url = "/admin/menu"
            return jsonify({"ok": True, "brand": brand, "redirect": redirect_url})

        allowed = parse_allowed_brands(me.get("allowed_brands"))
        if brand not in allowed:
            return jsonify({"ok": False, "error": "brand_not_allowed"}), 403

        set_brand(brand)
        redirect_url = "/staff/menu" if role in {"jefe_estacion", "operador", "contador", "auditor"} else "/mod/dashboard"
        return jsonify({"ok": True, "brand": brand, "redirect": redirect_url})





    @app.get("/staff/menu")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_menu():
        from services.brand import get_brand
        me = ctx.get_me() or {}
        role = (me.get("role") or "").strip().lower()
        cards = [
            {"title":"SASISOPA","subtitle":"Documentos recibidos y partes editables.","href":"/staff/sasisopa/docs/records","tag":"Módulo"},
            {"title":"SGM","subtitle":"Documentos recibidos y partes editables.","href":"/staff/sgm/docs/records","tag":"Módulo"},
            {"title":"Documentos faltantes","subtitle":"Sube faltantes para revisión y valida su estatus.","href":"/staff/pending-docs","tag":"Validación"},
            {"title":"Carpeta compartida","subtitle":"Archivos por estación con acceso controlado.","href":"/staff/shared-folder","tag":"Archivos"},
            {"title":"Organigrama","subtitle":"Consulta el organigrama corporativo en modo lectura.","href":"/mod/organigrama","tag":"Consulta"},
            {"title":"Dashboard","subtitle":"Resumen operativo del sistema activo.","href":"/mod/dashboard","tag":"Panel"},
            {"title":"Notificaciones","subtitle":"Avisos y seguimiento de pendientes.","href":"/mod/notifications","tag":"Avisos"},
        ]
        if role != "operador":
            cards.append({"title":"Mensualidad / Pagos","subtitle":"Consulta seguimiento financiero y comprobantes.","href":"/mod/payments","tag":"Control"})
        if role in {"contador","auditor"}:
            cards.append({"title":"Mapa / Estaciones","subtitle":"Vista global de estaciones del sistema activo.","href":"/mapa","tag":"Global"})
        return render_template("staff_menu_admin_like.html", brand=get_brand(), me=me, cards=cards)

    # SASISOPA (solo administradores)
    # Se conserva el path /staff por compatibilidad, pero restringido a admin.
    @app.get("/staff/sasisopa")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sasisopa_menu():
        return redirect("/staff/sasisopa/docs/records")

    @app.get("/staff/sasisopa/evidencia")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sasisopa_evidencia():
        return redirect("/staff/sasisopa/docs/records")

    @app.get("/staff/sasisopa/programa")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sasisopa_programa():
        return redirect("/staff/sasisopa/docs/records")

    @app.get("/staff/sasisopa/manual")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sasisopa_manual():
        return redirect("/staff/sasisopa/docs/records")

    @app.get("/staff/sasisopa/implementacion")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sasisopa_implementacion():
        return redirect("/staff/sasisopa/docs/records")

    @app.get("/admin/sasisopa")
    @login_required
    @role_required("admin")
    def admin_sasisopa_menu():
        return redirect("/admin/sasisopa/docs")

    @app.get("/admin/sasisopa/evidencia")
    @login_required
    @role_required("admin")
    def admin_sasisopa_evidencia():
        return redirect("/admin/sasisopa/docs")

    @app.get("/admin/sasisopa/programa")
    @login_required
    @role_required("admin")
    def admin_sasisopa_programa():
        return redirect("/admin/sasisopa/docs/templates")

    @app.get("/admin/sasisopa/manual")
    @login_required
    @role_required("admin")
    def admin_sasisopa_manual():
        return redirect("/admin/sasisopa/docs/templates")

    @app.get("/admin/sasisopa/implementacion")
    @login_required
    @role_required("admin")
    def admin_sasisopa_implementacion():
        return redirect("/admin/sasisopa/docs/reviews")

    
    @app.get("/admin/sasisopa/estudios")
    @login_required
    @role_required("admin")
    def admin_sasisopa_estudios():
        return redirect("/admin/sasisopa/docs/templates")

    @app.get("/admin/sasisopa/planos")
    @login_required
    @role_required("admin")
    def admin_sasisopa_planos():
        return redirect("/admin/sasisopa/docs/reviews")

    @app.get("/admin/sasisopa/historico")
    @login_required
    @role_required("admin")
    def admin_sasisopa_historico():
        return redirect("/admin/sasisopa/docs")

# SGM (Consulting documental)
    @app.get("/staff/sgm")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sgm_menu():
        return redirect("/staff/sgm/docs/records")

    @app.get("/staff/sgm/evidencia")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sgm_evidencia():
        return redirect("/staff/sgm/docs/records")

    @app.get("/staff/sgm/programa")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sgm_programa():
        return redirect("/staff/sgm/docs/records")

    @app.get("/staff/sgm/manual")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sgm_manual():
        return redirect("/staff/sgm/docs/records")

    @app.get("/staff/sgm/implementacion")
    @login_required
    @role_required("operador","jefe_estacion","contador","auditor")
    def staff_sgm_implementacion():
        return redirect("/staff/sgm/docs/records")

    @app.get("/admin/sgm")
    @login_required
    @role_required("admin")
    def admin_sgm_menu():
        return redirect("/admin/sgm/docs")

    @app.get("/admin/sgm/manual")
    @login_required
    @role_required("admin")
    def admin_sgm_manual():
        return redirect("/admin/sgm/docs/templates")

    @app.get("/admin/sgm/evidencia")
    @login_required
    @role_required("admin")
    def admin_sgm_evidencia():
        return redirect("/admin/sgm/docs")

    @app.get("/admin/sgm/programa")
    @login_required
    @role_required("admin")
    def admin_sgm_programa():
        return redirect("/admin/sgm/docs/templates")

    @app.get("/admin/sgm/implementacion")
    @login_required
    @role_required("admin")
    def admin_sgm_implementacion():
        return redirect("/admin/sgm/docs/reviews")


    @app.get("/admin/laboratorio")
    @login_required
    @role_required("admin")
    def admin_laboratorio():
        return render_template("admin/laboratorio.html")



    @app.route("/logout", methods=["GET", "POST"])
    def logout_page():
        me = ctx.get_me()
        session.clear()
        if me: ctx.log_action(me, "logout", "auth", str(me["id"]))
        return redirect("/login")

    @app.get("/dashboard")
    def dashboard_redirect():
        if not session.get("user_id"):
            return redirect("/login")
        return redirect("/mod/dashboard")

    # Module pages (separate screens)
    @app.get("/mod/<name>")
    def mod_page(name):
        if not session.get("user_id"):
            return redirect("/login")

        me = ctx.get_me() or {}
        role = me.get("role")

        # Restricciones por rol
        if name == "analytics" and role not in {"admin","auditor"}:
            return redirect("/mod/dashboard")
        if name in {"payments","reports"} and role == "operador":
            return redirect("/mod/dashboard")

        allowed = {
            "dashboard","analytics","activities","pipas","maintenance","alerts","payments","reports","profile","notifications"
        }
        if name not in allowed:
            abort(404)
        return render_template(f"mod/{name}.html")
    @app.get("/mod/bitacoras")
    def bitacoras_redirect():
        # Bitácora fue unificada con Actividades
        return redirect("/mod/activities")


    

    @app.get("/mod/activities/print")
    def activities_print_page():
        if not session.get("user_id"):
            return redirect("/login")
        me = ctx.get_me() or {}
        role = me.get("role")

        station_id = request.args.get("station_id")
        # operador/jefe: only their station
        if role != "admin":
            station_id = str(ctx.require_station(me))

        # Prefer explicit range (from calendar view)
        start_q = (request.args.get("start") or "").strip()
        end_q = (request.args.get("end") or "").strip()
        freq = (request.args.get("freq") or "").strip()
        q = (request.args.get("q") or "").strip().lower()

        if start_q:
            try:
                start = datetime.date.fromisoformat(start_q[:10])
            except Exception:
                start = datetime.date.today().replace(day=1)
        else:
            year = int(request.args.get("year") or datetime.date.today().year)
            month = int(request.args.get("month") or datetime.date.today().month)
            start = datetime.date(year, month, 1)

        if end_q:
            try:
                end = datetime.date.fromisoformat(end_q[:10])
            except Exception:
                end = (start + datetime.timedelta(days=32)).replace(day=1)
        else:
            # month end (exclusive)
            end = (start + datetime.timedelta(days=32)).replace(day=1)

        from db import get_conn
        from services.brand import get_brand
        conn = get_conn(); cur = conn.cursor()

        where = "ce.brand=? AND ce.start_date>=? AND ce.start_date<?"
        params = [get_brand(), start.isoformat(), end.isoformat()]

        if station_id:
            where += " AND (ce.station_id IS NULL OR ce.station_id=?)"
            params.append(int(station_id))

        if freq:
            where += " AND ce.repeat_kind=?"
            params.append(freq)

        cur.execute(
            "SELECT ce.id, ce.title, ce.start_date, ce.repeat_kind, a.description as description, s.code as station_code, s.name as station_name "
            "FROM calendar_events ce "
            "LEFT JOIN activities a ON a.id=ce.activity_id AND a.brand=ce.brand "
            "LEFT JOIN stations s ON s.id=ce.station_id AND s.brand=ce.brand "
            f"WHERE {where} "
            "ORDER BY ce.start_date ASC, ce.id ASC",
            tuple(params),
        )
        items=[dict(r) for r in cur.fetchall()]
        conn.close()

        # search filter (client-like)
        if q:
            def _match(it):
                t = (it.get("title") or "").lower()
                d = (it.get("description") or "").lower()
                stn = ((it.get("station_code") or "") + " " + (it.get("station_name") or "")).lower()
                return (q in t) or (q in d) or (q in stn)
            items = [it for it in items if _match(it)]

        return render_template(
            "mod/activities_print.html",
            start=start.isoformat(),
            end=end.isoformat(),
            freq=freq,
            q=q,
            station_id=station_id,
            items=items,
            me=me,
        )

    @app.get("/mod/activities/event/<int:event_id>")
    def activity_event_page(event_id: int):
        if not session.get("user_id"):
            return redirect("/login")
        # access is enforced in API; page just renders
        return render_template("mod/activity_event.html", event_id=event_id)

    @app.get("/admin/<name>")
    def admin_page(name):
        if not session.get("user_id"):
            return redirect("/login")
        me = ctx.get_me()
        if not me or me["role"] != "admin":
            return redirect("/mod/dashboard")
        allowed = {"inbox","users","stations","permissions","audit","backup"}
        if name not in allowed:
            abort(404)
        return render_template(f"admin/{name}.html")

    @app.get("/mapa")
    def mapa_page():
        if not session.get("user_id"):
            return redirect("/login")
        me = ctx.get_me()
        # only admin/contador/auditor can view the national map
        if me and me.get("role") not in {"admin","contador","auditor"}:
            return redirect("/mod/dashboard")
        return render_template("mapa.html")

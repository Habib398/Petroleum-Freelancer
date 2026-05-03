from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from urllib import request as urlreq
from urllib.parse import urljoin


def _get_branding_value(key: str, brand: str | None = None) -> str:
    try:
        from services.branding import get_setting_fallback
        return get_setting_fallback(key, brand=brand, default="")
    except Exception:
        return ""


def _truthy(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on", "si", "sí"}


def _mail_provider(brand: str | None = None) -> str:
    provider = (
        os.environ.get("COG_MAIL_PROVIDER")
        or os.environ.get("MAIL_PROVIDER")
        or _get_branding_value("mail_provider", brand)
        or "auto"
    )
    provider = provider.strip().lower()
    return provider if provider in {"auto", "ses", "smtp"} else "auto"


def _smtp_settings(brand: str | None = None) -> dict:
    host = (
        os.environ.get("COG_SMTP_HOST")
        or os.environ.get("MAIL_SMTP_HOST")
        or os.environ.get("SMTP_HOST")
        or _get_branding_value("smtp_host", brand)
        or ""
    ).strip()
    user = (
        os.environ.get("COG_SMTP_USER")
        or os.environ.get("MAIL_SMTP_USER")
        or os.environ.get("SMTP_USER")
        or _get_branding_value("smtp_user", brand)
        or ""
    ).strip()
    password = (
        os.environ.get("COG_SMTP_PASS")
        or os.environ.get("MAIL_SMTP_PASS")
        or os.environ.get("SMTP_PASS")
        or _get_branding_value("smtp_pass", brand)
        or ""
    ).strip()
    from_email = (
        os.environ.get("COG_SMTP_FROM")
        or os.environ.get("MAIL_FROM")
        or os.environ.get("SMTP_FROM")
        or _get_branding_value("smtp_from", brand)
        or user
        or ""
    ).strip()
    try:
        port = int(
            os.environ.get("COG_SMTP_PORT")
            or os.environ.get("MAIL_SMTP_PORT")
            or os.environ.get("SMTP_PORT")
            or _get_branding_value("smtp_port", brand)
            or "587"
        )
    except Exception:
        port = 587
    use_ssl = _truthy(os.environ.get("COG_SMTP_SSL") or os.environ.get("MAIL_SMTP_SSL") or os.environ.get("SMTP_SSL"), default=(port == 465)) or port == 465
    use_tls = _truthy(os.environ.get("COG_SMTP_TLS") or os.environ.get("MAIL_SMTP_TLS") or os.environ.get("SMTP_TLS"), default=True)
    return {
        "host": host,
        "user": user,
        "password": password,
        "from_email": from_email,
        "port": port,
        "use_ssl": use_ssl,
        "use_tls": use_tls,
    }


def _ses_settings(brand: str | None = None) -> dict:
    region = (
        os.environ.get("COG_SES_REGION")
        or os.environ.get("MAIL_SES_REGION")
        or os.environ.get("SES_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or _get_branding_value("ses_region", brand)
        or ""
    ).strip()
    from_email = (
        os.environ.get("COG_SES_FROM")
        or os.environ.get("MAIL_SES_FROM")
        or os.environ.get("SES_FROM_EMAIL")
        or _get_branding_value("ses_from", brand)
        or os.environ.get("MAIL_FROM")
        or _get_branding_value("smtp_from", brand)
        or ""
    ).strip()
    configuration_set = (
        os.environ.get("COG_SES_CONFIGURATION_SET")
        or os.environ.get("MAIL_SES_CONFIGURATION_SET")
        or os.environ.get("SES_CONFIGURATION_SET")
        or _get_branding_value("ses_configuration_set", brand)
        or ""
    ).strip()
    return {
        "region": region,
        "from_email": from_email,
        "configuration_set": configuration_set,
    }


def _normalize_attachments(attachments: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "archivo").strip() or "archivo"
        content = item.get("data")
        if content is None:
            continue
        if isinstance(content, str):
            content = content.encode("utf-8")
        try:
            payload = bytes(content)
        except Exception:
            continue
        normalized.append({
            "filename": filename,
            "data": payload,
            "mimetype": str(item.get("mimetype") or "application/octet-stream").strip() or "application/octet-stream",
        })
    return normalized


def _build_email_message(
    from_email: str,
    recipients: list[str],
    subject: str,
    body: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    html_body: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject or ""
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for att in _normalize_attachments(attachments):
        maintype, subtype = (att["mimetype"].split("/", 1) + ["octet-stream"])[:2]
        msg.add_attachment(att["data"], maintype=maintype or "application", subtype=subtype or "octet-stream", filename=att["filename"])
    return msg


def _send_via_smtp(
    recipients: list[str],
    subject: str,
    body: str,
    brand: str | None = None,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    html_body: str | None = None,
) -> tuple[bool, str]:
    cfg = _smtp_settings(brand)
    if not (cfg["host"] and cfg["user"] and cfg["password"] and cfg["from_email"] and recipients):
        return False, "smtp_not_configured"

    msg = _build_email_message(cfg["from_email"], recipients, subject, body, reply_to=reply_to, attachments=attachments, html_body=html_body)

    try:
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=12) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=12) as smtp:
                smtp.ehlo()
                if cfg["use_tls"]:
                    try:
                        smtp.starttls()
                        smtp.ehlo()
                    except Exception:
                        pass
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        return True, "sent_smtp"
    except Exception as exc:
        return False, f"smtp_error:{str(exc)[:400]}"


def _send_via_ses(
    recipients: list[str],
    subject: str,
    body: str,
    brand: str | None = None,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    html_body: str | None = None,
) -> tuple[bool, str]:
    cfg = _ses_settings(brand)
    if not (cfg["from_email"] and recipients):
        return False, "ses_not_configured"

    try:
        import boto3
    except Exception:
        return False, "ses_boto3_missing"

    client_kwargs = {}
    if cfg["region"]:
        client_kwargs["region_name"] = cfg["region"]

    try:
        client = boto3.client("ses", **client_kwargs)
        msg = _build_email_message(cfg["from_email"], recipients, subject, body, reply_to=reply_to, attachments=attachments, html_body=html_body)
        payload = {
            "Source": cfg["from_email"],
            "Destinations": recipients,
            "RawMessage": {"Data": msg.as_bytes()},
        }
        if cfg["configuration_set"]:
            payload["ConfigurationSetName"] = cfg["configuration_set"]
        client.send_raw_email(**payload)
        return True, "sent_ses"
    except Exception as exc:
        return False, f"ses_error:{str(exc)[:400]}"


def send_email_delivery(
    to_email: str | list[str] | tuple[str, ...],
    subject: str,
    body: str,
    brand: str | None = None,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    html_body: str | None = None,
) -> tuple[bool, str]:
    if isinstance(to_email, (list, tuple, set)):
        recipients = [str(item or "").strip() for item in to_email if str(item or "").strip()]
    else:
        recipients = [item.strip() for item in str(to_email or "").split(",") if item.strip()]
    if not recipients:
        return False, "missing_recipient"

    provider = _mail_provider(brand)
    attempts: list[tuple[str, tuple[bool, str]]] = []

    def try_provider(name: str) -> tuple[bool, str]:
        if name == "ses":
            return _send_via_ses(recipients, subject, body, brand=brand, reply_to=reply_to, attachments=attachments, html_body=html_body)
        return _send_via_smtp(recipients, subject, body, brand=brand, reply_to=reply_to, attachments=attachments, html_body=html_body)

    order = [provider] if provider in {"ses", "smtp"} else ["ses", "smtp"]
    for name in order:
        ok, detail = try_provider(name)
        attempts.append((name, (ok, detail)))
        if ok:
            return True, detail
        if detail.endswith("_not_configured"):
            continue

    details = " | ".join(f"{name}:{info[1]}" for name, info in attempts) or "mail_not_configured"
    return False, details


def send_email_if_configured(
    to_email: str | list[str] | tuple[str, ...],
    subject: str,
    body: str,
    brand: str | None = None,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    html_body: str | None = None,
) -> tuple[bool, str]:
    try:
        return send_email_delivery(to_email, subject, body, brand=brand, reply_to=reply_to, attachments=attachments, html_body=html_body)
    except Exception as exc:
        return False, f"mail_error:{str(exc)[:400]}"


def send_whatsapp_webhook_if_configured(payload: dict, brand: str | None = None) -> tuple[bool, str]:
    webhook_url = (
        os.environ.get("COG_WHATSAPP_WEBHOOK_URL")
        or os.environ.get("WHATSAPP_WEBHOOK_URL")
        or _get_branding_value("whatsapp_webhook_url", brand)
        or ""
    ).strip()
    if not webhook_url:
        return False, "whatsapp_not_configured"
    try:
        return _http_json(webhook_url, payload or {})
    except Exception as exc:
        return False, f"whatsapp_error:{str(exc)[:400]}"


def resolve_public_url(url: str, brand: str | None = None) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = (os.environ.get("COG_APP_URL") or _get_branding_value("app_url", brand)).strip()
    if not base:
        return url
    return urljoin(base.rstrip("/") + "/", url.lstrip("/"))


def build_notification_email_subject(brand: str, title: str) -> str:
    b = (brand or "consulting").strip().lower()
    brand_label = "Petroleum" if b == "petroleum" else "Consulting"
    ttl = (title or "Nueva notificación").strip()
    return f"[{brand_label}] {ttl}"


def build_notification_email_body(brand: str, title: str, body: str = "", url: str = "") -> str:
    b = (brand or "consulting").strip().lower()
    brand_label = "Petroleum" if b == "petroleum" else "Consulting"
    lines = [
        f"Sistema: {brand_label}",
        "",
        (title or "Nueva notificación").strip(),
    ]
    body = (body or "").strip()
    if body:
        lines.extend(["", body])
    final_url = resolve_public_url(url, brand=b)
    if final_url:
        lines.extend(["", f"Abrir: {final_url}"])
    return "\n".join(lines)


def _http_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 12) -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urlreq.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, body
    except Exception as exc:
        return False, str(exc)


def send_telegram_message(chat_id: str, text: str, token: str | None = None) -> tuple[bool, str]:
    token = (token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (chat_id or "").strip()
    if not token or not chat_id or not text:
        return False, "telegram_not_configured"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return _http_json(url, {"chat_id": chat_id, "text": text, "disable_web_page_preview": False})


def send_notification_to_user(user: dict, title: str, body: str = "", url: str = "", brand: str | None = None) -> dict:
    email = (user.get("email") or "").strip()
    telegram = (user.get("telegram_chat_id") or "").strip()
    result = {"email": {"ok": False, "detail": "missing_email"}, "telegram": {"ok": False, "detail": "missing_chat_id"}}
    if email:
        subject = build_notification_email_subject(brand or "consulting", title)
        ok, detail = send_email_delivery(email, subject, build_notification_email_body(brand or "consulting", title, body, url), brand=brand)
        result["email"] = {"ok": ok, "detail": detail}
    if telegram:
        text = f"{title}\n\n{body}".strip()
        final_url = resolve_public_url(url, brand=brand)
        if final_url:
            text += f"\n\nAbrir: {final_url}"
        ok, detail = send_telegram_message(telegram, text)
        result["telegram"] = {"ok": ok, "detail": detail}
    return result

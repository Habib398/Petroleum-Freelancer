from __future__ import annotations

import logging
import os
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, request, g


def _load_env_file(env_path: Path) -> None:
    """Small .env loader without extra dependency."""
    try:
        if not env_path.exists():
            return
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            os.environ[key] = value
    except Exception:
        pass


BASE_DIR = Path(__file__).resolve().parent
_load_env_file(BASE_DIR / ".env")

from db import get_conn, init_db
from services.context import AppContext
from services.scheduled import run_due_tick
from services.runtime_scheduler import start_runtime_scheduler
from services.branding import get_branding_settings, get_normative_config, get_normative_items, get_normative_titles_line
from services.storage import StorageService

# Módulos de dominio (arquitectura modular — cada módulo agrupa rutas afines)
import modules.auth as mod_auth
import modules.core as mod_core
import modules.stations as mod_stations
import modules.operations as mod_operations
import modules.compliance as mod_compliance
import modules.admin as mod_admin
import modules.petroleum as mod_petroleum


def _setup_logging(app: Flask, base_dir: Path) -> None:
    """Configure console + rotating file logs (CMD-friendly)."""
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Flask's app.logger already exists; attach handlers once
    app.logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Avoid duplicate handlers on reload / repeated app creation in tests
    has_file_handler = any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers)
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in app.logger.handlers
    )

    if not has_file_handler:
        file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        app.logger.addHandler(file_handler)

    if not has_console_handler:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(fmt)
        app.logger.addHandler(console)


def _wants_json() -> bool:
    # If it's an API call, always JSON
    if request.path.startswith("/api/"):
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept or "text/json" in accept


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.secret_key = os.environ.get("COG_SECRET") or os.environ.get("SECRET_KEY") or "change-this-secret-in-env"
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.environ.get("COG_SESSION_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=os.environ.get("COG_SESSION_SECURE", "0") == "1",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=os.environ.get("COG_SESSION_SECURE", "0") == "1",
    )
    # Global upper bound for uploads (per-endpoint limits are enforced in code).
    # - Default uploads: 20MB
    # - Annual evidence / annual uploads: higher (default 120MB)
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("COG_MAX_UPLOAD_MB", "120")) * 1024 * 1024

    # Per-module limits (MB)
    app.config["UPLOAD_LIMIT_DEFAULT_MB"] = int(os.environ.get("COG_UPLOAD_DEFAULT_MB", "20"))
    app.config["UPLOAD_LIMIT_ANNUAL_MB"] = int(os.environ.get("COG_UPLOAD_ANNUAL_MB", "120"))

    base_dir = BASE_DIR

    # Uploads
    upload_dir = Path(os.environ.get("COG_UPLOAD_DIR") or (base_dir / "uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Logs
    _setup_logging(app, base_dir)

    # DB init (creates tables + initial admin if needed)
    try:
        init_db()
    except Exception as e:
        app.logger.exception("DB init failed: %s", e)
        raise

    # Shared helpers for all route modules
    app.extensions["storage"] = StorageService(upload_dir=upload_dir)
    app.extensions["ctx"] = AppContext(upload_dir=upload_dir)
    # In-memory rate limit buckets (ok for single-process; for multi-worker use Redis)
    app.extensions["rate_login"] = {}
    app.extensions["rate_write"] = {}

    # --- Trace id for every request (helps pinpoint http_500 quickly) ---
    @app.before_request
    def _trace_id():
        g.trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex

        # CSRF token for any visitor (used by JS fetch wrapper)
        from flask import session
        if not session.get("csrf_token"):
            session["csrf_token"] = uuid.uuid4().hex
        g.csrf_token = session.get("csrf_token")

        # --- Enforce allowed brand (prevents cross-company data leaks) ---
        try:
            if session.get("user_id"):
                from db import get_user
                from services.brand import parse_allowed_brands, set_brand
                me = get_user(session.get("user_id")) or {}
                role = (me.get("role") or "").strip().lower()

                # Non-admin users can only operate inside their allowed brands
                if role != "admin":
                    allowed = parse_allowed_brands(me.get("allowed_brands"))
                    active = (session.get("brand") or "consulting").strip().lower()
                    if active not in allowed:
                        set_brand(sorted(list(allowed))[0] if allowed else "consulting")

                # Auto-activate Petroleum brand for Petroleum module URLs
                path_ = (request.path or "")
                if path_.startswith("/petroleum") or path_.startswith("/api/compliance") or path_.startswith("/api/petroleum/"):
                    allowed = {"consulting", "petroleum"} if role == "admin" else parse_allowed_brands(me.get("allowed_brands"))
                    if "petroleum" in allowed:
                        session["brand"] = "petroleum"
        except Exception:
            pass

        
        # Write rate limit (simple per-IP bucket)
        try:
            if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                # Skip login (has its own limiter)
                if request.path != "/api/auth/login":
                    import time
                    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or "unknown"
                    bucket = app.extensions.get("rate_write")
                    window = int(os.environ.get("COG_RL_WINDOW", "60") or 60)
                    limit = int(os.environ.get("COG_RL_WRITE", "240") or 240)
                    now = int(time.time())
                    rec = bucket.get(ip) if isinstance(bucket, dict) else None
                    if rec and now - rec.get("ts", 0) <= window and rec.get("count", 0) >= limit:
                        retry = max(1, window - (now - rec.get("ts", 0)))
                        return jsonify({"ok": False, "error": "rate_limited", "message": "Demasiadas solicitudes. Intenta más tarde.", "trace_id": getattr(g, "trace_id", "-")}), 429, {"Retry-After": str(retry)}
                    if isinstance(bucket, dict):
                        if not rec or now - rec.get("ts", 0) > window:
                            rec = {"ts": now, "count": 0}
                        rec["count"] = int(rec.get("count", 0)) + 1
                        rec["ts"] = rec.get("ts", now)
                        bucket[ip] = rec
        except Exception:
            pass

        # CSRF protection for state-changing requests
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if os.environ.get("COG_CSRF", "1") == "0":
                return None
            # Allow static assets and downloads
            if request.path.startswith("/static/") or request.path.startswith("/uploads/"):
                return None
            if request.path == "/api/auth/reset-password":
                return None
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not token or token != session.get("csrf_token"):
                if _wants_json() or request.path.startswith("/api/") or request.is_json:
                    return jsonify({
                        "ok": False,
                        "error": "csrf",
                        "message": "CSRF token inválido o faltante",
                        "trace_id": getattr(g, "trace_id", "-"),
                    }), 403
                return "CSRF token inválido", 403

    @app.after_request
    def _attach_trace_id(resp):
        try:
            resp.headers.setdefault("X-Trace-Id", getattr(g, "trace_id", "-"))
        except Exception:
            pass
        return resp

    # Opportunistic scheduler: run due/overdue checks periodically (throttled in DB)
    


    @app.after_request
    def _security_headers(resp):
        # Basic hardening headers (safe defaults for this app)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

        # Avoid stale UI / API caching (common source of "no se ven" inputs)
        if request.path.startswith(("/api/", "/admin", "/petroleum", "/mod", "/login", "/select-system")):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"

        # CSP: allow required CDNs for UI (FullCalendar + Google Fonts) while keeping a safe baseline.
        # Notes:
        # - FullCalendar is loaded from cdn.jsdelivr.net
        # - Inter font stylesheet comes from fonts.googleapis.com and font files from fonts.gstatic.com
        # - Some templates still use inline <style>/<script>
        csp = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
            "connect-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://unpkg.com; "
            "style-src-elem 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://unpkg.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "script-src-elem 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' data: https://fonts.gstatic.com;"
        )
        # IMPORTANT: overwrite (not setdefault). Some environments/middleware may
        # inject a stricter CSP earlier; we need the allowed CDNs for FullCalendar
        # and Google Fonts to render correctly.
        resp.headers["Content-Security-Policy"] = csp

        # HSTS only if behind HTTPS (common in hosting)
        if (request.headers.get("X-Forwarded-Proto") or "").lower() == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=15552000; includeSubDomains")
        return resp

    @app.after_request
    def _scheduled_ticks(resp):
        try:
            # Only on authenticated-ish app traffic; skip static/assets
            if request.path.startswith("/api/") or request.path.startswith("/admin"):
                run_due_tick(app.extensions["ctx"], logger=app.logger, min_interval_minutes=15)
        except Exception:
            # Never break responses
            pass
        return resp

    # --- Error handlers (prevents silent http_500) ---
    from werkzeug.exceptions import RequestEntityTooLarge

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(err):
        if _wants_json():
            return jsonify({
                "ok": False,
                "error": "file_too_large",
                "message": "Archivo demasiado grande",
                "trace_id": getattr(g, "trace_id", "-"),
            }), 413
        return "Archivo demasiado grande", 413
    @app.errorhandler(400)
    def bad_request(err):
        if _wants_json():
            return jsonify({"ok": False, "error": "bad_request", "message": str(err), "trace_id": getattr(g, "trace_id", "-")}), 400
        return err

    @app.errorhandler(401)
    def unauthorized(err):
        if _wants_json():
            return jsonify({"ok": False, "error": "unauthorized", "message": "No autorizado", "trace_id": getattr(g, "trace_id", "-")}), 401
        return err

    @app.errorhandler(403)
    def forbidden(err):
        if _wants_json():
            return jsonify({"ok": False, "error": "forbidden", "message": "Acceso denegado", "trace_id": getattr(g, "trace_id", "-")}), 403
        return err

    @app.errorhandler(404)
    def not_found(err):
        if _wants_json():
            return jsonify({"ok": False, "error": "not_found", "message": "No encontrado", "trace_id": getattr(g, "trace_id", "-")}), 404
        return err

    @app.errorhandler(Exception)
    def handle_exception(err):
        # Log full traceback to logs/app.log (with trace id)
        trace_id = getattr(g, "trace_id", "-")
        app.logger.exception("Unhandled exception [%s]: %s", trace_id, err)
        if _wants_json():
            payload = {
                "ok": False,
                "error": "server_error",
                "message": "Ocurrió un error interno. Revisa logs/app.log",
                "trace_id": trace_id,
            }
            # In debug mode, include a short error string to speed up fixing.
            if app.debug or os.environ.get("SHOW_ERROR_DETAILS") == "1":
                payload["details"] = str(err)
            resp = jsonify(payload)
            resp.headers["X-Trace-Id"] = trace_id
            return resp, 500
        # For HTML pages, return default error
        return err, 500

    # --- Healthcheck for CMD debugging ---
    @app.get("/api/health")
    def api_health():
        """Quick diagnostics: DB + uploads + tables."""
        status = {"ok": True, "db": {"ok": True}, "uploads": {"ok": True}, "tables": {}}
        # uploads
        try:
            test_file = upload_dir / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except Exception as e:
            status["ok"] = False
            status["uploads"] = {"ok": False, "error": str(e)}

        # db + tables
        tables = [
            "stations",
            "users",
            "calendar_events",
            "submissions",
            "pipas",
            "maintenance",
            "notifications",
        ]
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing = {r[0] for r in cur.fetchall()}
            for t in tables:
                status["tables"][t] = t in existing
                if t not in existing:
                    status["ok"] = False
            conn.close()
        except Exception as e:
            status["ok"] = False
            status["db"] = {"ok": False, "error": str(e)}

        return jsonify(status)

    # Registro de módulos de dominio
    mod_auth.register(app)        # Auth, usuarios y perfiles
    mod_core.register(app)        # Páginas, uploads, notificaciones, backup y extras
    mod_stations.register(app)    # Estaciones
    mod_operations.register(app)  # Actividades, pipas, mantenimiento, alertas, pagos
    mod_compliance.register(app)  # Documentos, normativas, CAPA y auditoría
    mod_admin.register(app)       # Admin, reportes, analítica y organigrama
    mod_petroleum.register(app)   # Funcionalidad exclusiva Petroleum

    # Inject CSRF token + branding into templates
    @app.context_processor
    def _inject_csrf():
        from flask import session
        active = (session.get("brand") or "consulting").strip().lower()
        return {
            "csrf_token": getattr(g, "csrf_token", ""),
            "brand_settings": get_branding_settings(active),
            "brand_cfg": get_branding_settings,
            "petroleum_norms": get_normative_config('petroleum'),
            "norm_cfg": get_normative_config,
            "norm_items": get_normative_items,
            "norm_titles_line": get_normative_titles_line,
        }

    if os.environ.get("COG_RUNTIME_SCHEDULER", "1") == "1":
        start_runtime_scheduler(app)
    return app


if __name__ == "__main__":
    app = create_app()
    debug = os.environ.get("APP_DEBUG", "0") == "1"
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=debug, use_reloader=debug)

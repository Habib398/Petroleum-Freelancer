from __future__ import annotations
import datetime, json, uuid
from pathlib import Path
from flask import session
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

from db import get_user, get_conn
from services.brand import get_brand
from services.storage import get_storage
from services.outbound import (
    build_notification_email_body,
    build_notification_email_subject,
    send_email_if_configured,
    send_whatsapp_webhook_if_configured,
)

class AppContext:
    """
    Shared helpers used across route modules.
    Stored on app.extensions['ctx'] inside create_app().
    """
    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir

    def now_iso(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def get_me(self):
        uid = session.get("user_id")
        if not uid:
            return None
        me = get_user(uid)
        if not me:
            session.clear()
            return None
        return me

    def login_required(self, fn):
        import functools
        from flask import jsonify
        @functools.wraps(fn)
        def w(*args, **kwargs):
            if not session.get("user_id"):
                return jsonify({"error": "not_authenticated"}), 401
            return fn(*args, **kwargs)
        return w

    def role_required(self, *roles):
        import functools
        from flask import jsonify
        def deco(fn):
            @functools.wraps(fn)
            def w(*args, **kwargs):
                me = self.get_me()
                if not me:
                    return jsonify({"error": "not_authenticated"}), 401
                if me.get("role") not in set(roles):
                    return jsonify({"error": "forbidden"}), 403
                return fn(*args, **kwargs)
            return w
        return deco

    def require_brand(self, fn):
        """Block access if the active session brand is not allowed for the user.

        - Admin: always allowed.
        - Others: session["brand"] must be in user.allowed_brands
        """
        import functools
        from flask import jsonify
        from services.brand import get_brand, user_allows_brand, parse_allowed_brands, set_brand

        @functools.wraps(fn)
        def w(*args, **kwargs):
            me = self.get_me()
            if not me:
                return jsonify({"error": "not_authenticated"}), 401
            if me.get("role") == "admin":
                return fn(*args, **kwargs)

            b = get_brand()
            if not user_allows_brand(me, b):
                allowed = parse_allowed_brands(me.get("allowed_brands"))
                if allowed:
                    set_brand(sorted(list(allowed))[0])
                return jsonify({"error": "brand_not_allowed"}), 403
            return fn(*args, **kwargs)
        return w

    def station_blocked(self, me: dict) -> bool:
        if me.get("role") == "admin":
            return False
        return me.get("monthly_status") in ("view_only", "expired")

    def require_station(self, me: dict) -> int:
        sid = me.get("station_id")
        if not sid:
            raise ValueError("user_has_no_station")
        return int(sid)


    def has_global_station_scope(self, me: dict) -> bool:
        if not me:
            return False
        role = (me.get("role") or "").strip().lower()
        if role == "admin":
            return True
        if role in {"contador", "auditor"} and not me.get("station_id"):
            return True
        return False

    def station_scope_ids(self, me: dict) -> set[int]:
        """Stations the user can access.

        - Admin: all stations for active brand.
        - Contador/Auditor without primary station: all stations for active brand.
        - Others: includes primary station_id + any delegated stations in user_station_access.
        """
        if not me:
            return set()
        if self.has_global_station_scope(me):
            try:
                conn = get_conn(); cur = conn.cursor()
                cur.execute("SELECT id FROM stations WHERE brand=?", (get_brand(),))
                ids = {int(r["id"]) for r in cur.fetchall()}
                conn.close()
                return ids
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                return set()
        scope: set[int] = set()
        if me.get("station_id"):
            try:
                scope.add(int(me["station_id"]))
            except Exception:
                pass
        try:
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                "SELECT station_id FROM user_station_access WHERE brand=? AND user_id=?",
                (get_brand(), int(me["id"])),
            )
            for r in cur.fetchall():
                try:
                    scope.add(int(r["station_id"]))
                except Exception:
                    pass
            conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        return scope

    def can_access_station(self, me: dict, station_id: int) -> bool:
        if not me:
            return False
        if self.has_global_station_scope(me):
            return True
        try:
            sid = int(station_id)
        except Exception:
            return False
        return sid in self.station_scope_ids(me)

    def log_action(self, me: dict | None, action: str, entity: str | None = None, entity_id: str | None = None, meta: dict | None = None):
        try:
            meta_obj = dict(meta or {})
            try:
                from flask import request, has_request_context
                if has_request_context():
                    meta_obj.setdefault("path", request.path)
                    meta_obj.setdefault("method", request.method)
                    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
                    if ip:
                        meta_obj.setdefault("ip", ip)
            except Exception:
                pass
            if me and me.get("username"):
                meta_obj.setdefault("actor_username", me.get("username"))
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO audit_log (brand, actor_user_id, action, entity, entity_id, meta_json) VALUES (?,?,?,?,?,?)",
                (get_brand(), me["id"] if me else None, action, entity, entity_id, json.dumps(meta_obj, ensure_ascii=False)),
            )
            conn.commit(); conn.close()
        except Exception:
            # Don't block user flows if audit logging fails.
            pass

    def sign_entity(self, me: dict | None, entity: str, entity_id: str | int, action: str, details: dict | None = None, brand: str | None = None):
        """Create an internal signature/audit stamp for approvals, submissions and reviews."""
        try:
            signer_ip = None
            try:
                from flask import request, has_request_context
                if has_request_context():
                    signer_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or None
            except Exception:
                signer_ip = None
            details_obj = dict(details or {})
            if me and me.get("username"):
                details_obj.setdefault("actor_username", me.get("username"))
            conn = get_conn(); cur = conn.cursor()
            cur.execute(
                "INSERT INTO internal_signatures (brand, entity, entity_id, action, signer_user_id, signer_name, signer_role, signer_ip, details_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    (brand or get_brand()),
                    (entity or "").strip(),
                    str(entity_id),
                    (action or "").strip(),
                    me.get("id") if me else None,
                    (me.get("username") if me else None),
                    (me.get("role") if me else None),
                    signer_ip,
                    json.dumps(details_obj, ensure_ascii=False),
                ),
            )
            conn.commit(); conn.close()
        except Exception:
            pass
    


    def _send_notification_emails_to_user_ids(self, conn, user_ids: list[int] | tuple[int, ...], brand: str, title: str, body: str = "", url: str = "") -> None:
        ids = sorted({int(uid) for uid in (user_ids or []) if uid})
        if not ids:
            return
        in_clause = ",".join(["?"] * len(ids))
        cur = conn.cursor()
        cur.execute(
            f"SELECT email FROM users WHERE is_active=1 AND id IN ({in_clause}) AND TRIM(COALESCE(email,''))<>''",
            tuple(ids),
        )
        subject = build_notification_email_subject(brand, title)
        email_body = build_notification_email_body(brand, title, body, url)
        seen = set()
        for r in cur.fetchall():
            email = (r.get("email") or "").strip()
            if not email:
                continue
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            send_email_if_configured(email, subject, email_body, brand=brand)

    def _send_notification_emails_for_scope(self, conn, brand: str, title: str, body: str = "", url: str = "", station_id=None) -> None:
        cur = conn.cursor()
        if station_id is None:
            cur.execute(
                "SELECT DISTINCT email FROM users WHERE is_active=1 AND TRIM(COALESCE(email,''))<>'' AND (allowed_brands LIKE ? OR primary_brand=? OR brand=?)",
                (f"%{brand}%", brand, brand),
            )
        else:
            sid = int(station_id)
            cur.execute(
                "SELECT DISTINCT u.email FROM users u "
                "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
                "WHERE u.is_active=1 AND TRIM(COALESCE(u.email,''))<>'' "
                "AND (u.role='admin' OR u.station_id=? OR usa.station_id=?) "
                "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
                (brand, sid, sid, f"%{brand}%", brand, brand),
            )
        subject = build_notification_email_subject(brand, title)
        email_body = build_notification_email_body(brand, title, body, url)
        seen = set()
        for r in cur.fetchall():
            email = (r.get("email") or "").strip()
            if not email:
                continue
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            send_email_if_configured(email, subject, email_body, brand=brand)

    def notify(self, user_id, station_id, title: str, body: str = "", url: str = "", ntype: str | None = None, brand: str | None = None):
        """Create an in-app notification.

        - If user_id is None, it is global.
        - brand defaults to the active session brand.
        """
        b = (brand or get_brand()).strip().lower()
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
            (b, user_id, station_id, ntype, title, body, url),
        )
        conn.commit()

        try:
            if user_id is None:
                self._send_notification_emails_for_scope(conn, b, title, body, url, station_id=station_id)
            else:
                self._send_notification_emails_to_user_ids(conn, [int(user_id)], b, title, body, url)
        except Exception:
            pass
        finally:
            conn.close()

        try:
            send_whatsapp_webhook_if_configured({
                "brand": b,
                "user_id": user_id,
                "station_id": station_id,
                "type": ntype,
                "title": title,
                "body": body,
                "url": url,
            }, brand=b)
        except Exception:
            pass

    def notify_admins(self, title: str, body: str = "", url: str = "", station_id=None, exclude_user_id: int | None = None, ntype: str | None = None, brand: str | None = None):
        """Notify all active admins (direct notifications).

        Admin users often have station_id NULL, so we cannot rely on notify_roles().
        """
        b = (brand or get_brand()).strip().lower()
        conn = get_conn(); cur = conn.cursor()
        sql = ("SELECT u.id FROM users u WHERE u.is_active=1 AND u.role='admin' \
               AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)")
        params: list = [f"%{b}%", b, b]
        if exclude_user_id is not None:
            sql += " AND u.id<>?"
            params.append(int(exclude_user_id))
        cur.execute(sql, tuple(params))
        admins = [int(r["id"]) for r in cur.fetchall()]
        for uid in admins:
            cur.execute(
                "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
                (b, uid, station_id, ntype, title, body, url),
            )
        conn.commit()
        try:
            self._send_notification_emails_to_user_ids(conn, admins, b, title, body, url)
        except Exception:
            pass
        conn.close()

    def notify_station_chiefs(self, station_id: int, title: str, body: str = "", url: str = "", exclude_user_id: int | None = None, ntype: str | None = None, brand: str | None = None):
        """Notify active station chiefs (jefe_estacion) for a specific station."""
        b = (brand or get_brand()).strip().lower()
        sid = int(station_id)
        conn = get_conn(); cur = conn.cursor()
        sql = ("SELECT DISTINCT u.id FROM users u \
               LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? \
               WHERE u.is_active=1 AND u.role='jefe_estacion' \
                 AND (u.station_id=? OR usa.station_id=?) \
                 AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)")
        params: list = [b, sid, sid, f"%{b}%", b, b]
        if exclude_user_id is not None:
            sql += " AND u.id<>?"
            params.append(int(exclude_user_id))
        cur.execute(sql, tuple(params))
        chiefs = [int(r["id"]) for r in cur.fetchall()]
        for uid in chiefs:
            cur.execute(
                "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
                (b, uid, sid, ntype, title, body, url),
            )
        conn.commit()
        try:
            self._send_notification_emails_to_user_ids(conn, chiefs, b, title, body, url)
        except Exception:
            pass
        conn.close()

    

    def notify_station_users(self, station_id: int, title: str, body: str = "", url: str = "", exclude_user_id: int | None = None, ntype: str | None = None, brand: str | None = None):
        """Notify all active users of a station (operador + jefe_estacion + auditor + contador).

        This is used for activity due/overdue notifications that must reach everyone in the station.
        Admins are not included here (use notify_admins for that).
        Includes delegated access (user_station_access) as well.
        """
        b = (brand or get_brand()).strip().lower()
        sid = int(station_id)
        conn = get_conn(); cur = conn.cursor()
        sql = (
            "SELECT DISTINCT u.id FROM users u "
            "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
            "WHERE u.is_active=1 AND u.role IN ('operador','jefe_estacion','auditor','contador') "
            "AND (u.station_id=? OR usa.station_id=?) "
            "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)"
        )
        params: list = [b, sid, sid, f"%{b}%", b, b]
        if exclude_user_id is not None:
            sql += " AND u.id<>?"
            params.append(int(exclude_user_id))
        cur.execute(sql, tuple(params))
        ids = [int(r["id"]) for r in cur.fetchall()]
        for uid in ids:
            cur.execute(
                "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
                (b, uid, sid, ntype, title, body, url),
            )
        conn.commit()
        try:
            self._send_notification_emails_to_user_ids(conn, ids, b, title, body, url)
        except Exception:
            pass
        conn.close()

    def notify_admins_and_station_chiefs(self, station_id: int, title: str, body: str = "", url: str = "", exclude_user_id: int | None = None, ntype: str | None = None, brand: str | None = None):
        """Notify admins + the chief(s) of a station (used for station-level alerts/mantenimientos/etc)."""
        sid = int(station_id)
        self.notify_admins(title, body, url, station_id=sid, exclude_user_id=exclude_user_id, ntype=ntype, brand=brand)
        self.notify_station_chiefs(sid, title, body, url, exclude_user_id=exclude_user_id, ntype=ntype, brand=brand)

    def notify_roles(self, station_id, roles: list[str], title: str, body: str = "", url: str = "", exclude_user_id: int | None = None, ntype: str | None = None, brand: str | None = None):
        """Notify active users by role.

        - If station_id is None: notifies all active users in those roles (with station_id).
        - Else: only users within that station.
        """
        if not roles:
            return
        b = (brand or get_brand()).strip().lower()
        conn = get_conn(); cur = conn.cursor()
        # Build IN clause safely
        in_clause = ",".join(["?"] * len(roles))
        sql = f"SELECT id, station_id FROM users WHERE is_active=1 AND role IN ({in_clause}) AND (allowed_brands LIKE ? OR primary_brand=? OR brand=?)"
        params: list = [*list(roles), f"%{b}%", b, b]

        if station_id is None:
            sql += " AND station_id IS NOT NULL"
        else:
            sql += " AND station_id=?"
            params.append(int(station_id))

        if exclude_user_id is not None:
            sql += " AND id<>?"
            params.append(int(exclude_user_id))

        cur.execute(sql, tuple(params))
        users = cur.fetchall()

        notified_ids = []
        for u in users:
            cur.execute(
                "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
                (b, u["id"], u["station_id"], ntype, title, body, url),
            )
            notified_ids.append(int(u["id"]))
        conn.commit()
        try:
            self._send_notification_emails_to_user_ids(conn, notified_ids, b, title, body, url)
        except Exception:
            pass
        conn.close()

    def notify_if_critical_audit(self, me: dict | None, action: str, entity: str | None = None):
        """Notify all admins if the action is in the CRITICAL_AUDIT_ACTIONS set."""
        CRITICAL_AUDIT_ACTIONS = {
            "change_role", "reset_password", "delete_user", "toggle_user",
            "restore_backup", "delete_backup",
            "grant_permission", "revoke_permission",
            "delete_station", "delete_document", "delete_correction_task",
            "update_user", "create_user",
        }
        if action not in CRITICAL_AUDIT_ACTIONS:
            return
        actor = (me.get("username") if me else "unknown") or "desconocido"
        title = "Acción de auditoría crítica"
        body = f"Usuario {actor} ejecutó '{action}' en {entity or 'sistema'}"
        self.notify_admins(title, body, "/admin/audit", ntype="audit", exclude_user_id=me.get("id") if me else None)

    def save_upload(self, fs, subdir: str) -> str:
        return self.save_upload_checked(fs, subdir=subdir)

    # ---------------- uploads (robust) ----------------
    def enforce_upload_limit(self, limit_mb: int):
        """Enforce size per request (works with multipart/form-data)."""
        try:
            clen = getattr(__import__("flask"), "request").content_length
            if clen is not None and int(clen) > int(limit_mb) * 1024 * 1024:
                raise RequestEntityTooLarge(f"Archivo demasiado grande. Límite: {limit_mb} MB")
        except RequestEntityTooLarge:
            raise
        except Exception:
            # If we cannot read content_length, rely on MAX_CONTENT_LENGTH
            return

    def _sniff_magic(self, fs) -> str:
        """Return a simple type string: pdf/png/jpg/unknown"""
        try:
            pos = fs.stream.tell()
        except Exception:
            pos = None
        head = b""
        try:
            head = fs.stream.read(16)
        except Exception:
            head = b""
        try:
            if pos is not None:
                fs.stream.seek(pos)
        except Exception:
            pass

        if head.startswith(b"%PDF"):
            return "pdf"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if head.startswith(b"\xff\xd8\xff"):
            return "jpg"
        return "unknown"

    def save_upload_checked(
        self,
        fs,
        subdir: str,
        allowed_ext: set[str] | None = None,
        limit_mb: int | None = None,
        allowed_magic: set[str] | None = None,
    ) -> str:
        """Save an uploaded file safely.

        - Validates extension and magic-bytes (optional)
        - Creates unique filename
        - Enforces per-endpoint size (optional)
        """
        if not fs or not getattr(fs, "filename", ""):
            return ""

        if limit_mb is not None:
            self.enforce_upload_limit(int(limit_mb))

        name = secure_filename(fs.filename or "")
        if not name:
            return ""
        ext = (Path(name).suffix or "").lower()
        if allowed_ext is not None and ext not in allowed_ext:
            raise ValueError("invalid_file_type")

        if allowed_magic is not None:
            magic = self._sniff_magic(fs)
            if magic not in allowed_magic:
                raise ValueError("invalid_file_type")

        # Unique name
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
        rand = uuid.uuid4().hex[:8]
        brand = (get_brand() or 'consulting').strip().lower()
        rel = f"{brand}/{subdir}/{stamp}_{rand}_{name}"
        get_storage().save_upload(fs, rel)
        return rel

    def require_fiel_for_annual(self, me: dict, station_id: int) -> bool:
        """Admin never needs FIEL. Only jefe_estacion needs FIEL for ANNUAL downloads.
        Local validation: profile fields present + cer/key present + updated within 365 days.
        """
        if me.get("role") == "admin":
            return True
        if me.get("role") != "jefe_estacion":
            return True
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "SELECT permit_number, legal_name, fiel_cer_path, fiel_key_path, fiel_updated_at FROM station_profiles WHERE station_id=?",
            (station_id,),
        )
        row = cur.fetchone(); conn.close()
        if not row:
            return False
        if not (row["permit_number"] and row["legal_name"] and row["fiel_cer_path"] and row["fiel_key_path"] and row["fiel_updated_at"]):
            return False
        try:
            upd = datetime.date.fromisoformat(row["fiel_updated_at"][:10])
            if (datetime.date.today() - upd).days > 365:
                return False
        except Exception:
            return False
        return True

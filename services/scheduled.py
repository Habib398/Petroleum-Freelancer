from __future__ import annotations

import datetime
import os
from pathlib import Path

from db import get_conn, DB_PATH
from flask import has_request_context
from services.backup import create_backup
from services.brand import VALID_BRANDS, get_brand
from services.deadlines import (
    list_document_deadlines,
    log_deadline_notification,
    notification_type_for_module,
    parse_reminder_days,
    route_for_module,
    sync_document_deadlines,
)
from services.outbound import (
    build_notification_email_body,
    build_notification_email_subject,
    send_email_if_configured,
)
from services.state import get_state as _get_state, set_state as _set_state
from services.utils import add_months as _add_months


# _add_months fue extraída a services/utils.py (importada como _add_months arriba)


def _next_date(cur: datetime.date, repeat: str) -> datetime.date | None:
    repeat = (repeat or "").strip().lower()
    if repeat == "daily":
        return cur + datetime.timedelta(days=1)
    if repeat == "weekly":
        return cur + datetime.timedelta(days=7)
    if repeat == "monthly":
        return _add_months(cur, 1)
    if repeat == "bimonthly":
        return _add_months(cur, 2)
    if repeat == "quarterly":
        return _add_months(cur, 3)
    if repeat == "fourmonthly":
        return _add_months(cur, 4)
    if repeat == "semiannual":
        return _add_months(cur, 6)
    if repeat == "yearly":
        return _add_months(cur, 12)
    if repeat == "fiveyearly":
        return _add_months(cur, 60)
    return None


def _extend_calendar_events(conn, brand: str, horizon_days: int = 60) -> int:
    """Create missing future events for recurring templates.

    This supports the "auto-generation" requirement: the system keeps
    generating future events without needing manual imports every month.

    Strategy:
    - For each activity with recurrence != once and is_active=1,
      find the latest calendar_event date for that activity+station scope.
    - Create events until today + horizon_days.
    """
    today = datetime.date.today()
    horizon = today + datetime.timedelta(days=horizon_days)
    cur = conn.cursor()
    created = 0

    cur.execute(
        "SELECT id, title, recurrence, target_station_id FROM activities WHERE brand=? AND is_active=1 AND recurrence IS NOT NULL AND recurrence<>'' AND recurrence<>'once'",
        (brand,),
    )
    acts = [dict(r) for r in cur.fetchall()]
    for a in acts:
        aid = int(a["id"])
        repeat = (a.get("recurrence") or "").strip().lower()
        station_id = a.get("target_station_id")

        # latest event
        if station_id is None:
            cur.execute(
                "SELECT MAX(start_date) AS mx FROM calendar_events WHERE brand=? AND activity_id=? AND station_id IS NULL",
                (brand, aid),
            )
        else:
            cur.execute(
                "SELECT MAX(start_date) AS mx FROM calendar_events WHERE brand=? AND activity_id=? AND station_id=?",
                (brand, aid, int(station_id)),
            )
        mx = (cur.fetchone()["mx"] or "")
        if not mx:
            continue
        try:
            last_dt = datetime.date.fromisoformat(mx[:10])
        except Exception:
            continue

        # create until horizon
        d = last_dt
        guard = 0
        while d < horizon and guard < 400:
            nd = _next_date(d, repeat)
            if not nd:
                break
            if nd > horizon:
                break
            # Insert if not exists
            if station_id is None:
                cur.execute(
                    "SELECT 1 FROM calendar_events WHERE brand=? AND activity_id=? AND station_id IS NULL AND start_date=? LIMIT 1",
                    (brand, aid, nd.isoformat()),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM calendar_events WHERE brand=? AND activity_id=? AND station_id=? AND start_date=? LIMIT 1",
                    (brand, aid, int(station_id), nd.isoformat()),
                )
            if cur.fetchone():
                d = nd
                guard += 1
                continue
            cur.execute(
                "INSERT INTO calendar_events (brand, activity_id, title, start_date, repeat_kind, station_id, created_by) VALUES (?,?,?,?,?,?,NULL)",
                (brand, aid, a.get("title") or "Actividad", nd.isoformat(), repeat, int(station_id) if station_id is not None else None),
            )
            created += 1
            d = nd
            guard += 1

    return created


# _get_state y _set_state fueron extraídas a services/state.py (importadas arriba)


def _dedup_key(conn, key: str) -> bool:
    """Return True if inserted (first time), False if already existed."""
    try:
        conn.execute("INSERT INTO notification_keys (key) VALUES (?)", (key,))
        return True
    except Exception:
        return False



def _send_notification_email_same_conn(conn, brand: str, user_id, title: str, body: str = "", url: str = "") -> None:
    if not user_id:
        return
    cur = conn.cursor()
    cur.execute(
        "SELECT email FROM users WHERE id=? AND is_active=1 AND TRIM(COALESCE(email,''))<>'' LIMIT 1",
        (int(user_id),),
    )
    row = cur.fetchone()
    if not row:
        return
    email = (row.get("email") or "").strip()
    if not email:
        return
    send_email_if_configured(
        email,
        build_notification_email_subject(brand, title),
        build_notification_email_body(brand, title, body, url),
        brand=brand,
    )


def _insert_notification(conn, brand: str, user_id, station_id, title: str, body: str, url: str, ntype: str | None = None) -> None:
    brand = (brand or "consulting").strip().lower()
    conn.execute(
        "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
        (brand, user_id, station_id, ntype, title, body, url),
    )
    try:
        _send_notification_email_same_conn(conn, brand, user_id, title, body, url)
    except Exception:
        pass


def _notify_admins_same_conn(conn, brand: str, title: str, body: str, url: str, station_id=None, ntype: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT u.id FROM users u WHERE u.is_active=1 AND u.role='admin' AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (f"%{brand}%", brand, brand),
    )
    for r in cur.fetchall():
        _insert_notification(conn, brand, int(r['id']), station_id, title, body, url, ntype)


def _notify_station_users_same_conn(conn, brand: str, station_id: int, title: str, body: str, url: str, ntype: str | None = None) -> None:
    sid = int(station_id)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT u.id FROM users u "
        "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
        "WHERE u.is_active=1 AND u.role IN ('operador','jefe_estacion','auditor','contador') "
        "AND (u.station_id=? OR usa.station_id=?) "
        "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (brand, sid, sid, f"%{brand}%", brand, brand),
    )
    for r in cur.fetchall():
        _insert_notification(conn, brand, int(r['id']), sid, title, body, url, ntype)


def _notify_station_chiefs_same_conn(conn, brand: str, station_id: int, title: str, body: str, url: str, ntype: str | None = None) -> None:
    """Notify only station chiefs (jefe_estacion) that can see this station."""
    sid = int(station_id)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT u.id FROM users u "
        "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
        "WHERE u.is_active=1 AND u.role='jefe_estacion' "
        "AND (u.station_id=? OR usa.station_id=?) "
        "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (brand, sid, sid, f"%{brand}%", brand, brand),
    )
    for r in cur.fetchall():
        _insert_notification(conn, brand, int(r["id"]), sid, title, body, url, ntype)


def _notify_station_operators_same_conn(conn, brand: str, station_id: int, title: str, body: str, url: str, ntype: str | None = None) -> None:
    """Notify only operators (operador) that can see this station."""
    sid = int(station_id)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT u.id FROM users u "
        "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
        "WHERE u.is_active=1 AND u.role='operador' "
        "AND (u.station_id=? OR usa.station_id=?) "
        "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (brand, sid, sid, f"%{brand}%", brand, brand),
    )
    for r in cur.fetchall():
        _insert_notification(conn, brand, int(r["id"]), sid, title, body, url, ntype)


def _date_from_text(value: str | None) -> datetime.date | None:
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except Exception:
        return None


def _renewal_notice_kind(due_date: datetime.date, today: datetime.date):
    if due_date < today:
        return 'overdue', 'Vencido para renovación'
    delta = (due_date - today).days
    if delta == 0:
        return 'today', 'Vence hoy'
    if delta in {1, 3, 7, 15, 30}:
        return f'due_{delta}d', f'Vence en {delta} día(s)'
    return None, None


def _collect_admin_ids_same_conn(conn, brand: str) -> set[int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT u.id FROM users u WHERE u.is_active=1 AND u.role='admin' AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (f"%{brand}%", brand, brand),
    )
    return {int(r['id']) for r in cur.fetchall()}


def _collect_station_role_ids_same_conn(conn, brand: str, station_id: int | None, roles: tuple[str, ...]) -> set[int]:
    sid = int(station_id or 0)
    if not sid or not roles:
        return set()
    cur = conn.cursor()
    placeholders = ','.join(['?'] * len(roles))
    cur.execute(
        "SELECT DISTINCT u.id FROM users u "
        "LEFT JOIN user_station_access usa ON usa.user_id=u.id AND usa.brand=? "
        f"WHERE u.is_active=1 AND u.role IN ({placeholders}) AND (u.station_id=? OR usa.station_id=?) "
        "AND (u.allowed_brands LIKE ? OR u.primary_brand=? OR u.brand=?)",
        (brand, *roles, sid, sid, f"%{brand}%", brand, brand),
    )
    return {int(r['id']) for r in cur.fetchall()}


def _notify_user_ids_same_conn(conn, brand: str, user_ids: set[int], station_id, title: str, body: str, url: str, ntype: str | None = None) -> None:
    for uid in sorted({int(x) for x in (user_ids or set()) if x}):
        _insert_notification(conn, brand, uid, station_id, title, body, url, ntype)


def run_due_tick(ctx, logger=None, min_interval_minutes: int = 15) -> None:
    """Scheduled-ish check for due/overdue activities.

    This runs opportunistically (on web requests), throttled by system_state.
    It creates station-level notifications for admins, plus payment due reminders for admins.
    """
    # Use UTC for throttling/state, but local time for "last hours" reminders
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    now_local = datetime.datetime.now()
    today = datetime.date.today()
    now_iso = now.isoformat(timespec="seconds")

    conn = get_conn()
    try:
        last = _get_state(conn, "due_tick_last")
        if last:
            try:
                last_dt = datetime.datetime.fromisoformat(last)
                if (now - last_dt).total_seconds() < min_interval_minutes * 60:
                    return
            except Exception:
                pass

        # Mark as running early (best effort)
        _set_state(conn, "due_tick_last", now.isoformat(timespec="seconds"))
        conn.commit()

        # ---- Daily backup (once per 24h, best-effort) ----
        try:
            disable_backup_tick = os.environ.get("COG_DISABLE_BACKUP_TICK", "0") == "1"
            db_path_str = str(DB_PATH or "").strip()
            ephemeral_db = db_path_str == ":memory:" or db_path_str.startswith("file:cog_memdb")
            if not disable_backup_tick and not ephemeral_db:
                last_b = _get_state(conn, "backup_last")
                do_backup = True
                if last_b:
                    try:
                        last_dt = datetime.datetime.fromisoformat(last_b)
                        do_backup = (now - last_dt).total_seconds() >= 24 * 3600
                    except Exception:
                        do_backup = True
                if do_backup:
                    base_dir = Path(ctx.upload_dir).resolve().parent
                    backup_result = create_backup(
                        base_dir, Path(DB_PATH), Path(ctx.upload_dir),
                        include_uploads=True, retention=7,
                        kind="scheduled", notes="daily auto backup",
                    )
                    _set_state(conn, "backup_last", now.isoformat(timespec="seconds"))
                    conn.commit()
                    if logger:
                        logger.info("daily backup created")
                    try:
                        _notify_admins_same_conn(conn, brand, "Respaldo automático completado", f"Respaldo diario creado: {backup_result.name if backup_result else 'desconocido'}", "/admin/backup", ntype="backup")
                    except Exception as e:
                        if logger:
                            logger.error(f"Failed to notify admins of backup: {e}")
        except Exception:
            # Never break main tick
            pass

        cur = conn.cursor()
        # In request-driven ticks, keep the current brand only. In background/runtime
        # ticks there is no request/session, so evaluate all brands safely.
        brands_to_check = [get_brand()] if has_request_context() else list(VALID_BRANDS)
        for brand in brands_to_check:
            # Station map (for nicer notification bodies).
            try:
                cur.execute("SELECT id, name FROM stations WHERE brand=?", (brand,))
                station_name_map = {int(r["id"]): (r["name"] or f"Estación {r['id']}") for r in cur.fetchall()}
            except Exception:
                station_name_map = {}
            # Auto-extend calendar events horizon (best-effort).
            try:
                created = _extend_calendar_events(conn, brand, horizon_days=60)
                if created and logger:
                    logger.info("auto-extended calendar events: brand=%s created=%s", brand, created)
            except Exception:
                pass

            try:
                sync_document_deadlines(conn, brand)
            except Exception:
                pass

            cur.execute("SELECT id FROM stations WHERE brand=?", (brand,))
            station_ids = [int(r["id"]) for r in cur.fetchall()]
            if not station_ids:
                continue

            # Evaluate each station
            for sid in station_ids:
                # All events applicable to this station
                cur.execute(
                    "SELECT id, start_date, title FROM calendar_events "
                    "WHERE brand=? AND (station_id IS NULL OR station_id=?) AND start_date IS NOT NULL",
                    (brand, sid),
                )
                events = [dict(r) for r in cur.fetchall()]

                # For each event, find latest submission status
                for ev in events:
                    try:
                        ev_date = datetime.date.fromisoformat((ev.get("start_date") or "")[:10])
                    except Exception:
                        continue

                    # Latest submission for this station + event
                    cur.execute(
                        "SELECT status FROM submissions WHERE brand=? AND station_id=? AND event_id=? ORDER BY id DESC LIMIT 1",
                        (brand, sid, int(ev["id"])),
                    )
                    srow = cur.fetchone()
                    latest = (srow["status"] if srow else None)

                    # Consider done only if approved
                    is_missing = (latest is None) or (latest == "rejected")
                    if not is_missing:
                        continue

                    # Determine bucket
                    key_kind = None
                    title = None
                    if ev_date < today:
                        key_kind = "overdue"
                        title = "Actividad vencida"
                    elif ev_date == today:
                        key_kind = "due_today"
                        title = "Actividad vence hoy"
                    else:
                        delta = (ev_date - today).days
                        if 1 <= delta <= 3:
                            key_kind = f"due_{delta}d"
                            title = "Actividad por vencer"

                    if not key_kind:
                        continue

                    dkey = f"due:{brand}:{sid}:{int(ev['id'])}:{key_kind}"
                    if not _dedup_key(conn, dkey):
                        continue

                    body = f"{ev_date.isoformat()} · {ev.get('title') or 'Actividad'} (evento #{ev['id']})"
                    # Activity due/overdue notifications reach admins
                    _notify_admins_same_conn(conn, brand, title, body, "/admin/inbox", station_id=sid, ntype="due")
                    # Also notify station users with different dedup key
                    dkey_users = f"due:station_users:{brand}:{sid}:{int(ev['id'])}:{key_kind}"
                    if _dedup_key(conn, dkey_users):
                        _notify_station_users_same_conn(conn, brand, int(sid), title, body, "/mod/operational-calendar", ntype="due")


            # ---- Documental SASISOPA/SGM due reminders (admins only) ----
            try:
                cur.execute(
                    "SELECT id, title, open_date, due_date, station_id, module "
                    "FROM doc_requirements "
                    "WHERE brand=? AND module IN ('sasisopa','sgm') AND status='OPEN' AND due_date IS NOT NULL",
                    (brand,),
                )
                for r in cur.fetchall():
                    rid = int(r["id"])
                    module = (r["module"] or "").strip().lower()
                    label = "SASISOPA" if module == "sasisopa" else ("SGM" if module == "sgm" else module.upper())
                    route = "sasisopa" if module == "sasisopa" else ("sgm" if module == "sgm" else module)
                    try:
                        open_d = datetime.date.fromisoformat((r["open_date"] or "")[:10])
                    except Exception:
                        open_d = today
                    try:
                        due_d = datetime.date.fromisoformat((r["due_date"] or "")[:10])
                    except Exception:
                        continue
                    if today < open_d:
                        continue

                    kind = None
                    ptitle = None
                    if due_d < today:
                        kind = "overdue"
                        ptitle = "Documento vencido"
                    elif due_d == today:
                        kind = "today"
                        ptitle = "Documento vence hoy"
                    else:
                        delta = (due_d - today).days
                        if 1 <= delta <= 3:
                            kind = f"due_{delta}d"
                            ptitle = "Documento por vencer"
                    if not kind:
                        continue

                    dkey = f"doc_due:{brand}:{module}:{rid}:{kind}:{due_d.isoformat()}"
                    if not _dedup_key(conn, dkey):
                        continue

                    sid = int(r["station_id"]) if r["station_id"] else None
                    st_name = station_name_map.get(sid) if sid else None
                    body = f"{due_d.isoformat()} · {r['title'] or 'Documento'}"
                    if st_name:
                        body += f" · {st_name}"
                    url = f"/admin/{route}/docs/reviews?requirement_id={rid}"
                    _notify_admins_same_conn(conn, brand, f"{label}: {ptitle}", body, url, station_id=sid, ntype="doc_due")
            except Exception:
                pass


            # ---- Documental SASISOPA/SGM last-hours reminders (chiefs + operators) ----
            # Goal: when there are only a few hours left and the document hasn't been uploaded,
            # notify the station chief(s) and the assigned operator (or all station operators if unassigned).
            try:
                cur.execute(
                    "SELECT id, title, open_date, due_date, station_id, assigned_user_id, module "
                    "FROM doc_requirements "
                    "WHERE brand=? AND module IN ('sasisopa','sgm') AND status='OPEN' AND due_date IS NOT NULL",
                    (brand,),
                )
                for r in cur.fetchall():
                    rid = int(r["id"])
                    module = (r["module"] or "").strip().lower()
                    label = "SASISOPA" if module == "sasisopa" else ("SGM" if module == "sgm" else module.upper())
                    route = "sasisopa" if module == "sasisopa" else ("sgm" if module == "sgm" else module)

                    sid = int(r["station_id"]) if r["station_id"] else None
                    if not sid:
                        # These reminders are station-centric.
                        continue

                    # Parse open/due as datetime. If only a date is provided, assume open at 00:00 and due at 23:59:59.
                    open_raw = (r["open_date"] or "").strip()
                    due_raw = (r["due_date"] or "").strip()
                    try:
                        if len(open_raw) >= 16:
                            open_dt = datetime.datetime.fromisoformat(open_raw.replace("Z", ""))
                        elif len(open_raw) >= 10:
                            open_dt = datetime.datetime.combine(datetime.date.fromisoformat(open_raw[:10]), datetime.time(0, 0, 0))
                        else:
                            open_dt = datetime.datetime.combine(today, datetime.time(0, 0, 0))
                    except Exception:
                        open_dt = datetime.datetime.combine(today, datetime.time(0, 0, 0))

                    try:
                        if len(due_raw) >= 16:
                            due_dt = datetime.datetime.fromisoformat(due_raw.replace("Z", ""))
                        else:
                            due_dt = datetime.datetime.combine(datetime.date.fromisoformat(due_raw[:10]), datetime.time(23, 59, 59))
                    except Exception:
                        continue

                    if now_local < open_dt:
                        continue

                    secs_left = (due_dt - now_local).total_seconds()
                    kind = None
                    ptitle = None
                    if 0 < secs_left <= 2 * 3600:
                        kind = "2h"
                        ptitle = "Últimas 2 horas para entregar"
                    elif 0 < secs_left <= 6 * 3600:
                        kind = "6h"
                        ptitle = "Últimas 6 horas para entregar"
                    elif secs_left <= 0:
                        # Notify once when it just became overdue (or when the tick catches it later)
                        kind = "overdue"
                        ptitle = "Documento vencido (no entregado)"

                    if not kind:
                        continue

                    # De-dupe per requirement + bucket + due hour.
                    hour_bucket = due_dt.strftime("%Y-%m-%dT%H")
                    dkey = f"doc_last_hours:{brand}:{module}:{rid}:{sid}:{kind}:{hour_bucket}"
                    if not _dedup_key(conn, dkey):
                        continue

                    st_name = station_name_map.get(sid) if sid else None
                    due_human = due_dt.strftime("%Y-%m-%d %H:%M")
                    body = f"{r['title'] or 'Documento'} · límite {due_human}"
                    if st_name:
                        body += f" · {st_name}"

                    # Staff link (for chiefs/operators to upload)
                    staff_url = f"/staff/{route}/docs/capture/{rid}"

                    # Notify station chief(s)
                    _notify_station_chiefs_same_conn(conn, brand, sid, f"{label}: {ptitle}", body, staff_url, ntype="doc_due_hours")

                    # Notify operator(s)
                    op_id = int(r["assigned_user_id"]) if r["assigned_user_id"] else None
                    if op_id:
                        _insert_notification(conn, brand, op_id, sid, f"{label}: {ptitle}", body, staff_url, ntype="doc_due_hours")
                    else:
                        _notify_station_operators_same_conn(conn, brand, sid, f"{label}: {ptitle}", body, staff_url, ntype="doc_due_hours")
            except Exception:
                pass


            # ---- Documental auto-reopen reminders (operator) ----
            try:
                cur.execute(
                    "SELECT ds.requirement_id, ds.operator_id, ds.module, ds.next_auto_reopen_at, dr.title, dr.station_id "
                    "FROM doc_submissions ds "
                    "JOIN doc_requirements dr ON dr.id=ds.requirement_id AND dr.brand=ds.brand AND dr.module=ds.module "
                    "WHERE ds.brand=? AND ds.review_status='WRONG' AND ds.attempt_no=1 "
                    "AND ds.next_auto_reopen_at IS NOT NULL AND ds.next_auto_reopen_at<=? "
                    "AND ds.module IN ('sasisopa','sgm') "
                    "AND NOT EXISTS (SELECT 1 FROM doc_submissions ds2 WHERE ds2.brand=ds.brand AND ds2.module=ds.module AND ds2.requirement_id=ds.requirement_id AND ds2.operator_id=ds.operator_id AND ds2.attempt_no=2)",
                    (brand, now_iso),
                )
                for r in cur.fetchall():
                    rid = int(r["requirement_id"])
                    uid = int(r["operator_id"])
                    module = (r["module"] or "").strip().lower()
                    label = "SASISOPA" if module == "sasisopa" else ("SGM" if module == "sgm" else module.upper())
                    route = "sasisopa" if module == "sasisopa" else ("sgm" if module == "sgm" else module)
                    dkey = f"doc_reopen:{brand}:{module}:{rid}:{uid}"
                    if not _dedup_key(conn, dkey):
                        continue
                    sid = int(r["station_id"]) if r["station_id"] else None
                    st_name = station_name_map.get(sid) if sid else None
                    body = f"{r['title'] or 'Documento'} · reintento disponible"
                    if st_name:
                        body += f" · {st_name}"
                    url = f"/staff/{route}/docs/capture/{rid}"
                    _insert_notification(conn, brand, uid, sid, f"{label}: Reintento disponible", body, url, ntype="doc_reopen")
            except Exception:
                pass


            # ---- Central document deadline reminders (deduplicated) ----
            try:
                reminder_rows = list_document_deadlines(conn, brand)
                for r in reminder_rows:
                    if not int(r.get('renewable') or 1):
                        continue
                    days_left = r.get('days_left')
                    if days_left is None:
                        continue
                    allowed_days = set(parse_reminder_days(r.get('reminder_days')))
                    if int(days_left) < 0:
                        notice_kind = 'overdue'
                    elif int(days_left) in allowed_days:
                        notice_kind = f"due_{int(days_left)}d"
                    else:
                        continue
                    sid = int(r['station_id']) if r.get('station_id') else None
                    title = f"{(r.get('module') or 'documento').replace('_',' ').title()}: {r.get('urgency_label') or 'Renovación pendiente'}"
                    body = f"{(r.get('title') or 'Documento').strip()} · vence {r.get('due_date') or ''}"
                    if r.get('folio'):
                        body += f" · {r['folio']}"
                    if r.get('scope_label'):
                        body += f" · {r['scope_label']}"
                    if r.get('notes'):
                        body += f" · {r['notes']}"
                    url = route_for_module(r.get('module'), is_admin=False if sid else True, brand=brand)
                    user_ids = _collect_admin_ids_same_conn(conn, brand)
                    if sid:
                        user_ids.update(_collect_station_role_ids_same_conn(conn, brand, sid, ('jefe_estacion',)))
                    if r.get('responsible_user_id'):
                        user_ids.add(int(r['responsible_user_id']))
                    for uid in sorted(user_ids):
                        if not log_deadline_notification(conn, int(r['id']), int(uid), notice_kind, 'in_app'):
                            continue
                        _insert_notification(conn, brand, int(uid), sid, title, body, url, ntype=notification_type_for_module(r.get('module')))
            except Exception:
                pass

            # Monthly payment reminders for admins only.
            cur.execute("SELECT id, name, monthly_status, monthly_end FROM stations WHERE brand=?", (brand,))
            for st in cur.fetchall():
                sid = int(st["id"])
                monthly_end = (st["monthly_end"] or "").strip() if st["monthly_end"] is not None else ""
                monthly_status = (st["monthly_status"] or "active").strip().lower()
                if not monthly_end or monthly_status == "view_only":
                    continue
                try:
                    due_date = datetime.date.fromisoformat(monthly_end[:10])
                except Exception:
                    continue

                kind = None
                ptitle = None
                if due_date < today:
                    kind = "overdue"
                    ptitle = "Mensualidad vencida"
                elif due_date == today:
                    kind = "today"
                    ptitle = "Mensualidad vence hoy"
                else:
                    delta = (due_date - today).days
                    if 1 <= delta <= 3:
                        kind = f"due_{delta}d"
                        ptitle = "Mensualidad por vencer"
                if not kind:
                    continue

                dkey = f"payment:{brand}:{sid}:{kind}:{due_date.isoformat()}"
                if not _dedup_key(conn, dkey):
                    continue

                station_name = (st["name"] or f"Estación {sid}").strip()
                body = f"{station_name} · fecha límite {due_date.isoformat()} · estado {monthly_status}"
                _notify_admins_same_conn(conn, brand, ptitle, body, "/admin/inbox", station_id=sid, ntype="payment")
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        if logger:
            logger.exception("due_tick failed: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass

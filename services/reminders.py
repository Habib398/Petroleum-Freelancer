from __future__ import annotations
import datetime
from db import get_conn
from services.brand import get_brand

def run_for_user(me: dict):
    """Create lightweight in-app reminders (idempotent per day) for upcoming/overdue activities."""
    if not me: 
        return
    role = me.get("role")
    if role == "admin":
        return
    station_id = me.get("station_id")
    if not station_id:
        return
    today = datetime.date.today().isoformat()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    brand = get_brand()

    conn = get_conn(); cur = conn.cursor()

    # Upcoming tomorrow events (per station or global)
    cur.execute("""
      SELECT ce.id, ce.title, ce.start_date
      FROM calendar_events ce
      WHERE ce.brand=? AND ce.start_date = ?
        AND (ce.station_id IS NULL OR ce.station_id = ?)
    """, (brand, tomorrow, station_id))
    upcoming = cur.fetchall()

    # Overdue (before today) without any submission (approved/submitted/reviewed)
    cur.execute("""
      SELECT ce.id, ce.title, ce.start_date
      FROM calendar_events ce
      LEFT JOIN submissions s
        ON s.event_id = ce.id AND s.station_id = ?
           AND s.status IN ('submitted','reviewed','approved')
      WHERE ce.brand=? AND ce.start_date < ?
        AND (ce.station_id IS NULL OR ce.station_id = ?)
        AND s.id IS NULL
    """, (station_id, brand, today, station_id))
    overdue = cur.fetchall()

    # idempotency: avoid duplicates for same day by checking notifications title+url+date
    def _exists(title, url):
        cur.execute("""
          SELECT 1 FROM notifications
          WHERE brand=? AND user_id=? AND title=? AND url=? AND substr(created_at,1,10)=?
          LIMIT 1
        """, (brand, me["id"], title, url, today))
        return cur.fetchone() is not None

    def _create(title, body, url):
        if _exists(title, url): 
            return
        cur.execute(
            "INSERT INTO notifications (brand, user_id, station_id, type, title, body, url) VALUES (?,?,?,?,?,?,?)",
            (brand, me["id"], station_id, "reminder", title, body, url),
        )

    for r in upcoming:
        _create("⏰ Actividad mañana", f'{r["title"]} ({r["start_date"]})', "/mod/activities")
    for r in overdue:
        _create("🚨 Actividad vencida", f'{r["title"]} ({r["start_date"]})', "/mod/activities")

    conn.commit(); conn.close()

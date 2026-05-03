from __future__ import annotations

import datetime

from db import get_conn


def create_correction_task(ctx, me: dict | None, *, brand: str, title: str, description: str = "", station_id=None, module: str = "", related_entity: str = "", related_entity_id: str = "", assigned_to=None, due_days: int = 3, source_status: str = "rejected", priority: str = "high") -> int | None:
    conn = get_conn(); cur = conn.cursor()
    due_date = (datetime.date.today() + datetime.timedelta(days=max(1, int(due_days or 3)))).isoformat()
    cur.execute(
        """
        INSERT INTO correction_tasks (
            brand, station_id, module, title, description, related_entity, related_entity_id,
            source_status, due_date, status, priority, created_by, assigned_to, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,'open',?,?,?,CURRENT_TIMESTAMP)
        """,
        (
            brand,
            int(station_id) if station_id else None,
            (module or "").strip() or None,
            (title or "Corrección requerida").strip(),
            (description or "").strip() or None,
            (related_entity or "").strip() or None,
            str(related_entity_id or "").strip() or None,
            (source_status or "rejected").strip(),
            due_date,
            (priority or "high").strip(),
            me.get("id") if me else None,
            int(assigned_to) if assigned_to else None,
        ),
    )
    task_id = int(cur.lastrowid)
    conn.commit(); conn.close()
    try:
        ctx.log_action(me, "create_correction_task", "correction_tasks", str(task_id), {
            "station_id": station_id,
            "module": module,
            "related_entity": related_entity,
            "related_entity_id": related_entity_id,
            "due_date": due_date,
        })
        ctx.sign_entity(me, "correction_task", str(task_id), "created", {
            "station_id": station_id,
            "module": module,
            "related_entity": related_entity,
            "related_entity_id": related_entity_id,
            "due_date": due_date,
        }, brand=brand)
        if assigned_to:
            ctx.notify(int(assigned_to), int(station_id) if station_id else None, "Nueva tarea de corrección", (title or "Corrección requerida")[:180], "/mod/corrections", ntype="correction_task", brand=brand)
        elif station_id:
            ctx.notify_admins_and_station_chiefs(int(station_id), "Nueva tarea de corrección", (title or "Corrección requerida")[:180], "/mod/corrections", exclude_user_id=(me.get("id") if me else None), ntype="correction_task", brand=brand)
    except Exception:
        pass
    return task_id

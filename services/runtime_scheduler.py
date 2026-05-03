from __future__ import annotations

import os
import threading
import time

from services.scheduled import run_due_tick


def start_runtime_scheduler(app) -> None:
    """Start a lightweight background scheduler thread.

    It complements the opportunistic tick and is skipped in testing/debug reload child duplication.
    """
    if getattr(app, "config", {}).get("TESTING"):
        return
    if os.environ.get("COG_DISABLE_RUNTIME_SCHEDULER", "0") == "1":
        return
    if app.extensions.get("runtime_scheduler_started"):
        return

    interval = max(60, int(os.environ.get("COG_RUNTIME_TICK_SECONDS", "300") or 300))

    # Avoid duplicate threads on Flask reloader parent process.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return

    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                with app.app_context():
                    run_due_tick(app.extensions["ctx"], logger=app.logger, min_interval_minutes=1)
            except Exception:
                try:
                    app.logger.exception("Runtime scheduler tick failed")
                except Exception:
                    pass
            stop_event.wait(interval)

    t = threading.Thread(target=_loop, name="cog-runtime-scheduler", daemon=True)
    t.start()
    app.extensions["runtime_scheduler_started"] = True
    app.extensions["runtime_scheduler_stop"] = stop_event

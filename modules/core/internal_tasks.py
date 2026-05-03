from __future__ import annotations

import os
from flask import Blueprint, jsonify, request
from services.scheduled import run_due_tick


def register(app):
    internal_bp = Blueprint("internal", __name__)
    secret = os.environ.get("COG_INTERNAL_SECRET", "change-me")

    @internal_bp.post("/api/internal/run-due-tick")
    def api_run_due_tick():
        token = request.headers.get("X-Internal-Secret") or request.args.get("secret")
        if not token or token != secret:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        run_due_tick(app.extensions["ctx"], logger=app.logger, min_interval_minutes=1)
        return jsonify({"ok": True})

    app.register_blueprint(internal_bp)

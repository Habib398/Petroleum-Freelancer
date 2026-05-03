from __future__ import annotations

import os
from pathlib import Path

from flask import jsonify, render_template, request, send_from_directory, current_app

from db import DB_PATH
from services.backup import create_backup, list_backups, restore_backup


def register(app):
    ctx = app.extensions["ctx"]
    login_required = ctx.login_required
    role_required = ctx.role_required

    @app.get("/admin/backup")
    @login_required
    @role_required("admin")
    def admin_backup_page():
        return render_template("admin/backup.html", me=ctx.get_me())

    @app.get("/api/admin/backups")
    @login_required
    @role_required("admin")
    def api_backups_list():
        base_dir = Path(current_app.root_path).resolve()
        return jsonify({"ok": True, "items": list_backups(base_dir)})

    @app.post("/api/admin/backups/create")
    @login_required
    @role_required("admin")
    def api_backups_create():
        base_dir = Path(current_app.root_path).resolve()
        out = create_backup(base_dir, Path(DB_PATH), Path(ctx.upload_dir), include_uploads=True, retention=7)
        ctx.log_action(ctx.get_me(), "create_backup", "backup", out.name, {"path": str(out)})
        return jsonify({"ok": True, "name": out.name})

    @app.get("/api/admin/backups/download/<name>")
    @login_required
    @role_required("admin")
    def api_backups_download(name: str):
        base_dir = Path(current_app.root_path).resolve()
        bdir = base_dir / "backups"
        # basic sanitization
        safe = os.path.basename(name)
        if not safe.endswith(".zip"):
            return jsonify({"ok": False, "error": "invalid_name"}), 400
        p = bdir / safe
        if not p.exists():
            return jsonify({"ok": False, "error": "not_found"}), 404
        ctx.log_action(ctx.get_me(), "download_backup", "backup", safe)
        return send_from_directory(bdir, safe, as_attachment=True, download_name=safe)

    @app.post("/api/admin/backups/restore")
    @login_required
    @role_required("admin")
    def api_backups_restore():
        # Safety confirmation
        confirm = (request.form.get("confirm") or "").strip().upper()
        if confirm != "RESTAURAR":
            return jsonify({"ok": False, "error": "confirm_required", "message": "Escribe RESTAURAR para confirmar"}), 400

        # Either restore from an existing backup name, or upload a zip
        name = (request.form.get("name") or "").strip()
        base_dir = Path(current_app.root_path).resolve()
        bdir = base_dir / "backups"

        zpath: Path | None = None
        if name:
            safe = os.path.basename(name)
            zpath = bdir / safe
        else:
            fs = request.files.get("file")
            if not fs or not (fs.filename or "").lower().endswith(".zip"):
                return jsonify({"ok": False, "error": "missing_zip"}), 400
            tmp = (bdir / f"_upload_restore_{os.urandom(4).hex()}.zip")
            bdir.mkdir(parents=True, exist_ok=True)
            fs.save(tmp)
            zpath = tmp

        try:
            restore_backup(zpath, Path(DB_PATH), Path(ctx.upload_dir), restore_uploads=True)
        finally:
            # remove temp uploaded file if used
            if name == "" and zpath and zpath.name.startswith("_upload_restore_"):
                try:
                    zpath.unlink(missing_ok=True)
                except Exception:
                    pass

        ctx.log_action(ctx.get_me(), "restore_backup", "backup", str(zpath.name if zpath else ""))
        return jsonify({"ok": True})

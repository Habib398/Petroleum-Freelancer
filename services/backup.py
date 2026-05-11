from __future__ import annotations

import datetime
import os
import shutil
import tempfile
import zipfile
from pathlib import Path


def backup_dir(base_dir: Path) -> Path:
    d = base_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_zip_add(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """Add a file to zip, ignoring race errors."""
    try:
        if path.is_file():
            zf.write(path, arcname)
    except Exception:
        pass


def create_backup(
    base_dir: Path,
    db_path: Path,
    uploads_dir: Path,
    *,
    include_uploads: bool = True,
    retention: int = 7,
    kind: str = "manual",
    triggered_by: int | None = None,
    notes: str | None = None,
) -> Path:
    """Create a ZIP backup containing DB (+ uploads optionally).

    Output: backend/backups/backup_YYYYMMDD_HHMMSS.zip

    Records the backup in the ``backup_logs`` table (best-effort: a logging
    failure never breaks the backup itself).
    """
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    out = backup_dir(base_dir) / f"backup_{ts}.zip"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()

    error_message: str | None = None
    try:
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # DB
            _safe_zip_add(zf, db_path, "data/cog_work_log.db")
            # Include WAL/SHM if present (helps consistent restore on SQLite WAL mode)
            for ext in ("-wal", "-shm"):
                p = Path(str(db_path) + ext)
                if p.exists():
                    _safe_zip_add(zf, p, f"data/cog_work_log.db{ext}")

            # Uploads
            if include_uploads and uploads_dir.exists():
                for root, _dirs, files in os.walk(uploads_dir):
                    r = Path(root)
                    for fn in files:
                        fp = r / fn
                        rel = fp.relative_to(uploads_dir)
                        _safe_zip_add(zf, fp, str(Path("uploads") / rel))

            # Manifest
            manifest = {
                "created_at_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "includes_uploads": bool(include_uploads),
            }
            zf.writestr("manifest.json", __import__("json").dumps(manifest, ensure_ascii=False, indent=2))

        shutil.move(tmp.name, out)
    except Exception as e:
        error_message = str(e)
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass

    # Retention: keep last N (only if backup succeeded)
    if error_message is None:
        try:
            items = sorted(backup_dir(base_dir).glob("backup_*.zip"), key=lambda p: p.name, reverse=True)
            for old in items[retention:]:
                try:
                    old.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

    # Best-effort logging in backup_logs (never let logging failures break the backup).
    try:
        from db import get_conn  # local import avoids circulars at module load time
        size = out.stat().st_size if (error_message is None and out.exists()) else None
        conn = get_conn()
        conn.execute(
            "INSERT INTO backup_logs (file_path, file_size_bytes, kind, triggered_by, notes, success, error_message) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(out), size, kind, triggered_by, notes, 0 if error_message else 1, error_message),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    if error_message is not None:
        raise RuntimeError(f"backup_failed: {error_message}")

    return out


def list_backups(base_dir: Path) -> list[dict]:
    out: list[dict] = []
    d = backup_dir(base_dir)
    for p in sorted(d.glob("backup_*.zip"), key=lambda x: x.name, reverse=True):
        try:
            out.append({
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            })
        except Exception:
            continue
    return out


def restore_backup(
    zip_path: Path,
    db_path: Path,
    uploads_dir: Path,
    *,
    restore_uploads: bool = True,
) -> None:
    """Restore DB (+ uploads) from a backup zip.

    This is destructive. It will:
    - Replace data/cog_work_log.db
    - Replace uploads/ (if restore_uploads=True)
    """
    if not zip_path.exists():
        raise FileNotFoundError("backup_not_found")

    tmpdir = Path(tempfile.mkdtemp(prefix="restore_backup_"))
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        # Replace DB
        new_db = tmpdir / "data" / "cog_work_log.db"
        if not new_db.exists():
            raise ValueError("backup_missing_db")

        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Safety copy
        if db_path.exists():
            shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
        shutil.copy2(new_db, db_path)

        # Restore WAL/SHM if present
        for ext in ("-wal", "-shm"):
            src = tmpdir / "data" / f"cog_work_log.db{ext}"
            dst = Path(str(db_path) + ext)
            if src.exists():
                shutil.copy2(src, dst)
            else:
                try:
                    dst.unlink(missing_ok=True)
                except Exception:
                    pass

        # Replace uploads
        if restore_uploads:
            src_up = tmpdir / "uploads"
            if uploads_dir.exists():
                shutil.rmtree(uploads_dir, ignore_errors=True)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            if src_up.exists():
                shutil.copytree(src_up, uploads_dir, dirs_exist_ok=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

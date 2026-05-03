from __future__ import annotations

import io
import mimetypes
import os
from pathlib import Path

from flask import current_app, send_file, send_from_directory

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None


class StorageService:
    """Simple local/S3 storage abstraction.

    - local mode: files are stored under upload_dir
    - s3 mode: files are stored in S3 and cached locally under upload_dir
    """

    def __init__(self, upload_dir: Path):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.mode = (os.environ.get("COG_STORAGE_MODE") or "local").strip().lower()
        self.bucket = (os.environ.get("COG_S3_BUCKET") or "").strip()
        self.prefix = (os.environ.get("COG_S3_PREFIX") or "").strip().strip("/")
        self.region = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1").strip()
        self.endpoint_url = (os.environ.get("COG_S3_ENDPOINT_URL") or "").strip() or None
        self.cache_local = (os.environ.get("COG_STORAGE_CACHE_LOCAL", "1") == "1")
        self._client = None

        if self.mode == "s3":
            if not self.bucket:
                raise RuntimeError("COG_STORAGE_MODE=s3 requiere COG_S3_BUCKET")
            if boto3 is None:
                raise RuntimeError("boto3 no está instalado para usar almacenamiento S3")
            self._client = boto3.client("s3", region_name=self.region, endpoint_url=self.endpoint_url)
        else:
            self.mode = "local"

    def normalize_relpath(self, relpath: str) -> str:
        rel = str(relpath or "").replace("\\", "/").strip("/")
        if not rel:
            raise ValueError("relpath vacío")
        return rel

    def object_key(self, relpath: str) -> str:
        rel = self.normalize_relpath(relpath)
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def local_path(self, relpath: str) -> Path:
        return self.upload_dir / self.normalize_relpath(relpath)

    def save_upload(self, fs, relpath: str, content_type: str | None = None) -> str:
        rel = self.normalize_relpath(relpath)
        if self.mode == "local":
            dest = self.local_path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            fs.save(dest)
            return rel

        raw = fs.read()
        try:
            fs.stream.seek(0)
        except Exception:
            pass
        return self.save_bytes(raw, rel, content_type=content_type or getattr(fs, "mimetype", None))

    def save_bytes(self, raw: bytes, relpath: str, content_type: str | None = None) -> str:
        rel = self.normalize_relpath(relpath)
        if self.mode == "local":
            dest = self.local_path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            return rel

        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        assert self._client is not None
        self._client.put_object(Bucket=self.bucket, Key=self.object_key(rel), Body=raw, **extra)
        if self.cache_local:
            dest = self.local_path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        return rel

    def upload_local_file(self, src: Path, relpath: str, content_type: str | None = None) -> str:
        rel = self.normalize_relpath(relpath)
        if self.mode == "local":
            dest = self.local_path(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != dest.resolve():
                dest.write_bytes(src.read_bytes())
            return rel
        return self.save_bytes(src.read_bytes(), rel, content_type=content_type)

    def ensure_local(self, relpath: str) -> Path:
        rel = self.normalize_relpath(relpath)
        dest = self.local_path(rel)
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == "local":
            return dest
        assert self._client is not None
        self._client.download_file(self.bucket, self.object_key(rel), str(dest))
        return dest

    def exists(self, relpath: str) -> bool:
        rel = self.normalize_relpath(relpath)
        if self.local_path(rel).exists():
            return True
        if self.mode == "local":
            return False
        try:
            assert self._client is not None
            self._client.head_object(Bucket=self.bucket, Key=self.object_key(rel))
            return True
        except Exception:
            return False

    def delete(self, relpath: str) -> None:
        rel = self.normalize_relpath(relpath)
        try:
            self.local_path(rel).unlink(missing_ok=True)
        except Exception:
            pass
        if self.mode == "s3":
            try:
                assert self._client is not None
                self._client.delete_object(Bucket=self.bucket, Key=self.object_key(rel))
            except Exception:
                pass

    def send(self, relpath: str, *, as_attachment: bool = True, download_name: str | None = None):
        rel = self.normalize_relpath(relpath)
        if self.mode == "local":
            return send_from_directory(self.upload_dir, rel, as_attachment=as_attachment, download_name=download_name)
        local = self.ensure_local(rel)
        guessed = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        return send_file(local, mimetype=guessed, as_attachment=as_attachment, download_name=download_name or local.name, conditional=True)


def get_storage() -> StorageService:
    return current_app.extensions["storage"]

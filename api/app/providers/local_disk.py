"""Local filesystem storage fallback for dev when R2 isn't configured."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from api.app.config import settings


class LocalDiskProvider:
    """Stores files on the local filesystem under data/storage/."""

    def __init__(self, base_dir: str = "data/storage") -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        return self._base / key

    def _meta_path(self, key: str) -> Path:
        return self._base / f"{key}.meta.json"

    async def upload(
        self,
        identity_id: str,
        product: str,
        file_type: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        key = f"{identity_id}/{product}/{file_type}/{filename}"
        file_id = str(uuid.uuid4())

        path = self._file_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        meta = {
            "file_id": file_id,
            "key": key,
            "size": len(data),
            "content_type": content_type,
            "identity_id": identity_id,
            "product": product,
            "file_type": file_type,
            "upload_time": int(time.time()),
            "metadata": metadata or {},
        }
        self._meta_path(key).write_text(json.dumps(meta))

        return {
            "file_id": file_id,
            "key": key,
            "size": len(data),
            "content_type": content_type,
        }

    async def download(self, key: str) -> tuple[bytes, str]:
        path = self._file_path(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {key}")
        data = path.read_bytes()
        content_type = "application/octet-stream"
        meta_path = self._meta_path(key)
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            content_type = meta.get("content_type", content_type)
        return data, content_type

    async def delete(self, key: str) -> bool:
        path = self._file_path(key)
        meta_path = self._meta_path(key)
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        if meta_path.exists():
            meta_path.unlink()
        return deleted

    async def list_files(
        self,
        identity_id: str,
        product: str | None = None,
        prefix: str | None = None,
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        search_dir = self._base / identity_id
        if product:
            search_dir = search_dir / product
        if prefix:
            search_dir = search_dir / prefix

        files = []
        if search_dir.exists():
            for path in sorted(search_dir.rglob("*")):
                if path.is_file() and not path.name.endswith(".meta.json"):
                    rel = str(path.relative_to(self._base))
                    stat = path.stat()
                    files.append({
                        "key": rel,
                        "size": stat.st_size,
                        "last_modified": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
                        ),
                    })

        # Simple pagination via offset
        offset = int(continuation_token) if continuation_token else 0
        page = files[offset : offset + max_keys]
        next_offset = offset + max_keys
        truncated = next_offset < len(files)

        return {
            "files": page,
            "total": len(page),
            "next_token": str(next_offset) if truncated else None,
            "truncated": truncated,
        }

    async def usage(self, identity_id: str) -> dict[str, Any]:
        user_dir = self._base / identity_id
        total_size = 0
        file_count = 0
        if user_dir.exists():
            for path in user_dir.rglob("*"):
                if path.is_file() and not path.name.endswith(".meta.json"):
                    total_size += path.stat().st_size
                    file_count += 1
        return {
            "used_bytes": total_size,
            "file_count": file_count,
            "quota_bytes": settings.default_storage_quota,
        }

    async def health(self) -> bool:
        return self._base.exists()

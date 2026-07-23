"""Cloudflare R2 storage adapter — boto3 S3-compatible.

Port of Windy Pro's account-server/src/services/r2-adapter.ts.
Same bucket structure, same metadata tags.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from api.app.config import settings

# Internal tag keys that user metadata must not overwrite
_RESERVED_TAG_KEYS = frozenset(
    {
        "windy-user-id",
        "windy-file-type",
        "windy-upload-time",
        "windy-product",
        "windy-file-id",
    }
)


class StorageProvider(Protocol):
    """Interface all storage providers implement."""

    async def upload(
        self,
        identity_id: str,
        product: str,
        file_type: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...

    async def download(self, key: str) -> tuple[bytes, str]: ...

    async def delete(self, key: str) -> bool: ...

    async def list_files(
        self,
        identity_id: str,
        product: str | None = None,
        prefix: str | None = None,
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> dict[str, Any]: ...

    async def usage(self, identity_id: str) -> dict[str, Any]: ...

    async def health(self) -> bool: ...


class R2StorageProvider:
    """Cloudflare R2 via boto3. Mirrors Pro's r2-adapter.ts bucket layout."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )
        self._bucket = settings.r2_bucket

    def _build_key(self, identity_id: str, product: str, file_type: str, filename: str) -> str:
        return f"{identity_id}/{product}/{file_type}/{filename}"

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
        key = self._build_key(identity_id, product, file_type, filename)
        file_id = str(uuid.uuid4())
        tags = {
            "windy-user-id": identity_id,
            "windy-file-type": file_type,
            "windy-upload-time": str(int(time.time())),
            "windy-product": product,
            "windy-file-id": file_id,
        }
        if metadata:
            # Filter out reserved internal tags to prevent user overwrite.
            # Coerce every value to str: S3/R2 object metadata is str→str,
            # and boto3's validate_ascii_metadata calls .encode() on each
            # value — a bool/int (callers send e.g. encrypted=True,
            # size_bytes=123, retention_count=5) raised
            # "AttributeError: 'bool' object has no attribute 'encode'" →
            # 500 on every real backup. Metadata comes back as strings on
            # download anyway, so stringifying here is lossless.
            tags.update({k: str(v) for k, v in metadata.items() if k not in _RESERVED_TAG_KEYS})

        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata=tags,
        )
        return {
            "file_id": file_id,
            "key": key,
            "size": len(data),
            "content_type": content_type,
        }

    async def download(self, key: str) -> tuple[bytes, str]:
        resp = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        data = resp["Body"].read()
        content_type = resp.get("ContentType", "application/octet-stream")
        return data, content_type

    async def delete(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    async def list_files(
        self,
        identity_id: str,
        product: str | None = None,
        prefix: str | None = None,
        max_keys: int = 100,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        search_prefix = f"{identity_id}/"
        if product:
            search_prefix += f"{product}/"
        if prefix:
            search_prefix += prefix

        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Prefix": search_prefix,
            "MaxKeys": max_keys,
        }
        if continuation_token:
            params["ContinuationToken"] = continuation_token

        resp = await asyncio.to_thread(self._client.list_objects_v2, **params)
        files = []
        for obj in resp.get("Contents", []):
            files.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
            )
        return {
            "files": files,
            "total": resp.get("KeyCount", 0),
            "next_token": resp.get("NextContinuationToken"),
            "truncated": resp.get("IsTruncated", False),
        }

    async def usage(self, identity_id: str) -> dict[str, Any]:
        total_size = 0
        file_count = 0
        token = None
        while True:
            result = await self.list_files(identity_id, max_keys=1000, continuation_token=token)
            for f in result["files"]:
                total_size += f["size"]
                file_count += 1
            if not result["truncated"]:
                break
            token = result["next_token"]
        return {
            "used_bytes": total_size,
            "file_count": file_count,
            "quota_bytes": settings.default_storage_quota,
        }

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return True
        except ClientError:
            return False
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Unexpected R2 health check error")
            return False

"""R2 object metadata must be str→str (2026-07-06 regression).

The archive route passes a metadata dict with non-string values
(encrypted=True bool, size_bytes/retention_count ints) into
provider.upload. S3/R2 metadata must be strings, and boto3's
validate_ascii_metadata calls .encode() on each value — a bool/int
raised "AttributeError: 'bool' object has no attribute 'encode'" → 500
on every real agent backup (only reachable once the auth + timeout bugs
were fixed). The provider must coerce all values to str.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_upload_stringifies_non_string_metadata():
    with patch("api.app.providers.r2.boto3") as mock_boto3:
        client = MagicMock()
        mock_boto3.client.return_value = client
        from api.app.providers.r2 import R2StorageProvider

        provider = R2StorageProvider()
        await provider.upload(
            identity_id="ET26-T11V-NPD1",
            product="windy_fly",
            file_type="agent",
            filename="windyfly-x.enc",
            data=b"ciphertext",
            content_type="application/octet-stream",
            # the exact shape cloud_backup sends — bools + ints
            metadata={
                "encrypted": True,
                "compressed": "gzip",
                "size_bytes": 123,
                "retention_count": 5,
            },
        )

        _, kwargs = client.put_object.call_args
        meta = kwargs["Metadata"]
        # Every value must be a str (this is what boto3's ascii-validate
        # + S3 require); bools/ints coerced, not passed through raw.
        assert all(isinstance(v, str) for v in meta.values()), meta
        assert meta["encrypted"] == "True"
        assert meta["size_bytes"] == "123"
        assert meta["retention_count"] == "5"
        assert meta["compressed"] == "gzip"

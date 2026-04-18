"""Product-specific archive endpoints with retention support."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.webhook import get_user_or_service, require_not_frozen, verify_service_token
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import FileRecord
from api.app.models.storage import (
    ArchiveResponse,
    MigrateRequest,
    MigrateResponse,
    MigrateResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-worker upload concurrency limit. Bounds how many archive uploads
# one Fargate task will process concurrently; on an autoscaled fleet
# the effective fleet-wide concurrency is `5 * N_tasks`. Edge rate
# limits (ALB / WAF) are the right knob for fleet-wide caps; this
# semaphore exists so one task's memory stays bounded under a burst.
# GAP G29 tracks making the per-worker nature explicit in the name.
_upload_semaphore = asyncio.Semaphore(5)


def _sanitize_filename(name: str) -> str:
    """Strip path traversal characters and normalize filename."""
    name = name.replace("\\", "/")
    name = name.split("/")[-1]
    name = re.sub(r"\.{2,}", ".", name)
    name = name.strip(". ")
    return name or str(uuid.uuid4())


# Valid product/type combinations
ARCHIVE_TYPES = {
    "chat": {"product": "windy_chat", "type": "chat_backup"},
    "mail": {"product": "windy_mail", "type": "mail_backup"},
    "agent": {"product": "windy_fly", "type": "agent_backup"},
    "recordings": {"product": "windy_pro", "type": "recording"},
    "code-settings": {"product": "windy_code", "type": "settings"},
}


def _get_provider():
    if settings.r2_configured:
        from api.app.providers.r2 import R2StorageProvider

        return R2StorageProvider()
    from api.app.providers.local_disk import LocalDiskProvider

    return LocalDiskProvider()


async def _enforce_retention(
    db: AsyncSession,
    provider,
    identity_id: str,
    product: str,
    file_type: str,
    retention_count: int | None,
) -> None:
    """Delete oldest files beyond retention_count for this identity/product/type."""
    if not retention_count or retention_count <= 0:
        return

    result = await db.execute(
        select(FileRecord)
        .where(
            FileRecord.identity_id == identity_id,
            FileRecord.product == product,
            FileRecord.file_type == file_type,
        )
        .order_by(FileRecord.created_at.desc())
    )
    records = list(result.scalars().all())
    if len(records) <= retention_count:
        return

    to_delete = records[retention_count:]
    for record in to_delete:
        await provider.delete(record.storage_key)
        await db.delete(record)


async def _archive_upload(
    archive_key: str,
    file: UploadFile,
    metadata: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> ArchiveResponse:
    """Shared logic for all archive endpoints."""
    async with _upload_semaphore:
        return await _do_archive_upload(archive_key, file, metadata, user, db)


async def _do_archive_upload(
    archive_key: str,
    file: UploadFile,
    metadata: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> ArchiveResponse:
    config = ARCHIVE_TYPES[archive_key]
    product = config["product"]
    file_type = config["type"]

    data = await file.read()
    if len(data) > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size} bytes",
        )

    try:
        extra = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in metadata field")
    encrypted = extra.get("encrypted", False)
    retention_count = extra.get("retention_count")
    retention_days = extra.get("retention_days")

    filename = _sanitize_filename(file.filename or f"{file_type}_{uuid.uuid4()}")
    content_type = file.content_type or "application/octet-stream"

    provider = _get_provider()
    result = await provider.upload(
        identity_id=user.identity_id,
        product=product,
        file_type=file_type,
        filename=filename,
        data=data,
        content_type=content_type,
        metadata=extra,
    )

    record = FileRecord(
        id=result["file_id"],
        identity_id=user.identity_id,
        product=product,
        file_type=file_type,
        filename=filename,
        storage_key=result["key"],
        size_bytes=result["size"],
        content_type=content_type,
        encrypted=encrypted,
        metadata_json=metadata if metadata != "{}" else None,
        retention_count=retention_count,
        retention_days=retention_days,
    )
    db.add(record)
    await db.flush()

    # Enforce retention (delete oldest beyond limit)
    await _enforce_retention(db, provider, user.identity_id, product, file_type, retention_count)
    await db.commit()

    return ArchiveResponse(
        file_id=result["file_id"],
        key=result["key"],
        product=product,
        type=file_type,
        size=result["size"],
    )


@router.post("/chat", response_model=ArchiveResponse)
async def archive_chat(
    file: UploadFile = File(...),
    metadata: str = Form('{"encrypted": true, "retention_count": 7}'),
    user: AuthenticatedUser = Depends(get_user_or_service),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("chat", file, metadata, user, db)


@router.post("/mail", response_model=ArchiveResponse)
async def archive_mail(
    file: UploadFile = File(...),
    metadata: str = Form('{"retention_days": 90}'),
    user: AuthenticatedUser = Depends(get_user_or_service),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("mail", file, metadata, user, db)


@router.post("/agent", response_model=ArchiveResponse)
async def archive_agent(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_user_or_service),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("agent", file, metadata, user, db)


@router.post("/recordings", response_model=ArchiveResponse)
async def archive_recordings(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_user_or_service),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("recordings", file, metadata, user, db)


@router.post("/code-settings", response_model=ArchiveResponse)
async def archive_code_settings(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_user_or_service),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("code-settings", file, metadata, user, db)


@router.post(
    "/migrate",
    response_model=MigrateResponse,
    dependencies=[Depends(verify_service_token)],
)
async def archive_migrate(
    body: MigrateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Hot → cold storage migration. Products call this to archive files to R2.

    Service-token authenticated (X-Service-Token) — this is a product
    backend → cloud batch operation, not a user-facing endpoint.
    Wave 2 missed this route when switching the other /archive/*
    endpoints to `get_user_or_service`; Wave 7 G13 completes the
    conversion by gating it on the shared service token. Products
    name the target identity via `body.windy_identity_id`.

    Accepts file metadata (not the file bytes) — products should call
    POST /api/v1/storage/upload for each file first, then call this to
    register the migration and set retention policies.
    """
    # Validate product
    valid_products = {v["product"] for v in ARCHIVE_TYPES.values()}
    if body.product not in valid_products and body.product != "general":
        raise HTTPException(status_code=400, detail=f"Unknown product: {body.product}")

    results = []
    for file_entry in body.files:
        filename = _sanitize_filename(file_entry.filename)

        # Check if file already exists in cold storage
        existing = await db.execute(
            select(FileRecord).where(
                FileRecord.identity_id == body.windy_identity_id,
                FileRecord.product == body.product,
                FileRecord.filename == filename,
            )
        )
        record = existing.scalar_one_or_none()

        if record:
            # Already migrated — update retention if specified
            if file_entry.retention_days is not None:
                record.retention_days = file_entry.retention_days
            if file_entry.retention_count is not None:
                record.retention_count = file_entry.retention_count
            results.append(
                MigrateResult(
                    filename=filename,
                    file_id=record.id,
                    key=record.storage_key,
                    size=record.size_bytes,
                    status="already_exists",
                )
            )
        else:
            # Register migration record — file was already uploaded via storage/upload
            file_id = str(uuid.uuid4())
            key = f"{body.windy_identity_id}/{body.product}/archive/{filename}"
            new_record = FileRecord(
                id=file_id,
                identity_id=body.windy_identity_id,
                product=body.product,
                file_type="archive",
                filename=filename,
                storage_key=key,
                size_bytes=file_entry.size,
                content_type=file_entry.content_type,
                encrypted=file_entry.encrypted,
                retention_days=file_entry.retention_days,
                retention_count=file_entry.retention_count,
            )
            db.add(new_record)
            results.append(
                MigrateResult(
                    filename=filename,
                    file_id=file_id,
                    key=key,
                    size=file_entry.size,
                    status="migrated",
                )
            )

    await db.commit()
    return MigrateResponse(
        product=body.product,
        identity_id=body.windy_identity_id,
        migrated=len([r for r in results if r.status == "migrated"]),
        results=results,
    )


@router.get("/retrieve/{product}/{filename:path}")
async def archive_retrieve(
    product: str,
    filename: str,
    user: AuthenticatedUser = Depends(require_not_frozen),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a file from cold storage. Used when a product needs archived data back.

    Example: user requests an old email, archived recording, or agent backup.
    """
    filename = _sanitize_filename(filename)

    result = await db.execute(
        select(FileRecord).where(
            FileRecord.identity_id == user.identity_id,
            FileRecord.product == product,
            FileRecord.filename == filename,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Archived file not found")

    provider = _get_provider()
    try:
        data, content_type = await provider.download(record.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found in storage backend")
    except Exception:
        logger.exception("Cold storage retrieval failed for key %s", record.storage_key)
        raise HTTPException(status_code=502, detail="Storage backend error")

    safe_name = (
        record.filename.replace("\\", "_").replace('"', "_").replace("\n", "_").replace("\r", "_")
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )

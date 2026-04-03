"""Product-specific archive endpoints with retention support."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import FileRecord
from api.app.models.storage import ArchiveResponse

router = APIRouter()

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
    config = ARCHIVE_TYPES[archive_key]
    product = config["product"]
    file_type = config["type"]

    data = await file.read()
    if len(data) > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size} bytes",
        )

    extra = json.loads(metadata) if metadata else {}
    encrypted = extra.get("encrypted", False)
    retention_count = extra.get("retention_count")
    retention_days = extra.get("retention_days")

    filename = file.filename or f"{file_type}_{uuid.uuid4()}"
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
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("chat", file, metadata, user, db)


@router.post("/mail", response_model=ArchiveResponse)
async def archive_mail(
    file: UploadFile = File(...),
    metadata: str = Form('{"retention_days": 90}'),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("mail", file, metadata, user, db)


@router.post("/agent", response_model=ArchiveResponse)
async def archive_agent(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("agent", file, metadata, user, db)


@router.post("/recordings", response_model=ArchiveResponse)
async def archive_recordings(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("recordings", file, metadata, user, db)


@router.post("/code-settings", response_model=ArchiveResponse)
async def archive_code_settings(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _archive_upload("code-settings", file, metadata, user, db)

"""Storage endpoints — upload, list, download, delete, usage/quota."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import FileRecord
from api.app.models.storage import (
    DeleteResponse,
    FileInfo,
    FileListResponse,
    StoragePlan,
    StoragePlansResponse,
    UploadResponse,
    UsageResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Limit concurrent uploads to prevent memory exhaustion (files can be up to 1 GB)
_upload_semaphore = asyncio.Semaphore(5)


def _sanitize_filename(name: str) -> str:
    """Strip path traversal characters and normalize filename."""
    # Remove path separators and traversal
    name = name.replace("\\", "/")
    name = name.split("/")[-1]  # Take only the basename
    name = re.sub(r"\.{2,}", ".", name)  # Collapse consecutive dots
    name = name.strip(". ")
    return name or str(uuid.uuid4())


def _get_provider():
    """Return the active storage provider (R2 or local disk)."""
    if settings.r2_configured:
        from api.app.providers.r2 import R2StorageProvider

        return R2StorageProvider()
    from api.app.providers.local_disk import LocalDiskProvider

    return LocalDiskProvider()


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    product: str = Form("general"),
    file_type: str = Form("file"),
    metadata: str = Form("{}"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async with _upload_semaphore:
        return await _do_upload(file, product, file_type, metadata, user, db)


async def _do_upload(
    file: UploadFile,
    product: str,
    file_type: str,
    metadata: str,
    user: AuthenticatedUser,
    db: AsyncSession,
) -> UploadResponse:
    data = await file.read()
    if len(data) > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size} bytes",
        )

    # Check quota
    usage_row = await db.execute(
        select(func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
            FileRecord.identity_id == user.identity_id
        )
    )
    current_usage = usage_row.scalar() or 0
    if current_usage + len(data) > settings.default_storage_quota:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Storage quota exceeded",
        )

    filename = _sanitize_filename(file.filename or f"{uuid.uuid4()}")
    content_type = file.content_type or "application/octet-stream"
    try:
        extra_meta = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in metadata field")

    provider = _get_provider()
    result = await provider.upload(
        identity_id=user.identity_id,
        product=product,
        file_type=file_type,
        filename=filename,
        data=data,
        content_type=content_type,
        metadata=extra_meta,
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
        metadata_json=metadata if metadata != "{}" else None,
    )
    db.add(record)
    await db.commit()

    return UploadResponse(**result)


@router.get("/files", response_model=FileListResponse)
async def list_files(
    product: str | None = Query(None),
    file_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(FileRecord).where(FileRecord.identity_id == user.identity_id)
    count_query = select(func.count(FileRecord.id)).where(
        FileRecord.identity_id == user.identity_id
    )

    if product:
        query = query.where(FileRecord.product == product)
        count_query = count_query.where(FileRecord.product == product)
    if file_type:
        query = query.where(FileRecord.file_type == file_type)
        count_query = count_query.where(FileRecord.file_type == file_type)

    query = query.order_by(FileRecord.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    records = result.scalars().all()
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    files = [
        FileInfo(
            file_id=r.id,
            product=r.product,
            file_type=r.file_type,
            filename=r.filename,
            storage_key=r.storage_key,
            size_bytes=r.size_bytes,
            content_type=r.content_type,
            encrypted=r.encrypted,
            created_at=r.created_at,
        )
        for r in records
    ]
    return FileListResponse(
        files=files,
        total=total,
        truncated=(offset + limit) < total,
        next_token=str(offset + limit) if (offset + limit) < total else None,
    )


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.identity_id == user.identity_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    provider = _get_provider()
    try:
        data, content_type = await provider.download(record.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found in storage")
    except Exception:
        logger.exception("Storage download failed for key %s", record.storage_key)
        raise HTTPException(status_code=502, detail="Storage backend error")

    # Sanitize filename for Content-Disposition header (prevent header injection)
    safe_name = (
        record.filename.replace("\\", "_").replace('"', "_").replace("\n", "_").replace("\r", "_")
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


@router.delete("/files/{file_id}", response_model=DeleteResponse)
async def delete_file(
    file_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.identity_id == user.identity_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    provider = _get_provider()
    await provider.delete(record.storage_key)
    await db.delete(record)
    await db.commit()

    return DeleteResponse(deleted=True, file_id=file_id)


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        ).where(FileRecord.identity_id == user.identity_id)
    )
    row = result.one()
    used_bytes = row[0]
    file_count = row[1]
    quota = settings.default_storage_quota
    return UsageResponse(
        used_bytes=used_bytes,
        file_count=file_count,
        quota_bytes=quota,
        used_percent=round((used_bytes / quota) * 100, 2) if quota > 0 else 0,
    )


STORAGE_PLANS = [
    StoragePlan(
        plan_id="free",
        name="Free",
        storage_bytes=524_288_000,
        storage_display="500 MB",
        price_cents_per_month=0,
        price_display="Free",
    ),
    StoragePlan(
        plan_id="basic",
        name="Basic",
        storage_bytes=5_368_709_120,
        storage_display="5 GB",
        price_cents_per_month=200,
        price_display="$2/mo",
    ),
    StoragePlan(
        plan_id="pro",
        name="Pro",
        storage_bytes=53_687_091_200,
        storage_display="50 GB",
        price_cents_per_month=500,
        price_display="$5/mo",
    ),
    StoragePlan(
        plan_id="ultra",
        name="Ultra",
        storage_bytes=214_748_364_800,
        storage_display="200 GB",
        price_cents_per_month=1000,
        price_display="$10/mo",
    ),
]


@router.get("/breakdown")
async def storage_breakdown(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-product storage breakdown for dashboard chart."""
    result = await db.execute(
        select(
            FileRecord.product,
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        )
        .where(FileRecord.identity_id == user.identity_id)
        .group_by(FileRecord.product)
    )
    products = []
    for product, total_bytes, file_count in result.all():
        products.append({"product": product, "bytes": total_bytes, "file_count": file_count})
    return {"products": products}


@router.get("/export")
async def export_data(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Package all user files into a ZIP for GDPR data export."""
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    result = await db.execute(
        select(FileRecord)
        .where(FileRecord.identity_id == user.identity_id)
        .order_by(FileRecord.product, FileRecord.created_at)
    )
    records = result.scalars().all()

    provider = _get_provider()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for record in records:
            try:
                data, _ = await provider.download(record.storage_key)
                path = f"{record.product}/{record.file_type}/{record.filename}"
                zf.writestr(path, data)
            except Exception:
                logger.warning("Skipping file %s in export", record.storage_key)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="windy-cloud-export.zip"'},
    )


@router.get("/plans", response_model=StoragePlansResponse)
async def storage_plans():
    """Public endpoint — no auth required. Returns storage tier pricing."""
    return StoragePlansResponse(plans=STORAGE_PLANS)


@router.get("/health")
async def storage_health():
    provider = _get_provider()
    ok = await provider.health()
    return {"status": "ok" if ok else "degraded", "provider": type(provider).__name__}

"""Data export endpoints — GDPR-compliant full data download."""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.db.engine import async_session, get_db
from api.app.db.models import ExportJob, FileRecord

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_provider():
    from api.app.config import settings

    if settings.r2_configured:
        from api.app.providers.r2 import R2StorageProvider

        return R2StorageProvider()
    from api.app.providers.local_disk import LocalDiskProvider

    return LocalDiskProvider()


async def _run_export(job_id: str, identity_id: str) -> None:
    """Background task: package all user files into a ZIP and store it."""
    async with async_session() as db:
        # Load job
        result = await db.execute(select(ExportJob).where(ExportJob.id == job_id))
        job = result.scalar_one()
        job.status = "processing"
        await db.commit()

        try:
            # Get all files
            result = await db.execute(
                select(FileRecord)
                .where(FileRecord.identity_id == identity_id)
                .order_by(FileRecord.product, FileRecord.created_at)
            )
            records = result.scalars().all()
            job.total_files = len(records)
            await db.commit()

            provider = _get_provider()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, record in enumerate(records):
                    try:
                        data, _ = await provider.download(record.storage_key)
                        path = f"{record.product}/{record.file_type}/{record.filename}"
                        zf.writestr(path, data)
                    except Exception:
                        logger.warning("Skipping file %s in export", record.storage_key)
                    job.processed_files = i + 1
                    await db.commit()

            # Store the ZIP as a file
            zip_data = buf.getvalue()
            export_filename = f"export_{identity_id}_{job_id[:8]}.zip"
            result = await provider.upload(
                identity_id=identity_id,
                product="system",
                file_type="export",
                filename=export_filename,
                data=zip_data,
                content_type="application/zip",
            )

            job.status = "completed"
            job.download_key = result["key"]
            job.completed_at = datetime.now(timezone.utc)
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            await db.commit()
            logger.info("Export %s completed: %d files", job_id, len(records))

        except Exception:
            logger.exception("Export job %s failed", job_id)
            job.status = "failed"
            job.error = "Internal error during export"
            await db.commit()


@router.post("/my-data")
async def request_export(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request a full data export. Returns a job_id to poll for completion."""
    # Check for existing pending/processing export
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.identity_id == user.identity_id,
            ExportJob.status.in_(["pending", "processing"]),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {
            "job_id": existing.id,
            "status": existing.status,
            "total_files": existing.total_files,
            "processed_files": existing.processed_files,
            "message": "Export already in progress",
        }

    job = ExportJob(identity_id=user.identity_id)
    db.add(job)
    await db.commit()

    # Launch background task
    asyncio.create_task(_run_export(job.id, user.identity_id))

    return {
        "job_id": job.id,
        "status": "pending",
        "total_files": 0,
        "processed_files": 0,
        "message": "Export started — poll GET /api/v1/export/{job_id} for progress",
    }


@router.get("/{job_id}")
async def get_export_status(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll export job status. When completed, includes download_url."""
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.identity_id == user.identity_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    resp: dict = {
        "job_id": job.id,
        "status": job.status,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "created_at": job.created_at.isoformat(),
    }

    if job.status == "completed" and job.download_key:
        resp["download_url"] = f"/api/v1/storage/files/export/{job.download_key}"
        resp["expires_at"] = job.expires_at.isoformat() if job.expires_at else None
        resp["completed_at"] = job.completed_at.isoformat() if job.completed_at else None

    if job.status == "failed":
        resp["error"] = job.error

    # Progress percentage
    if job.total_files > 0:
        resp["progress_percent"] = round(job.processed_files / job.total_files * 100)
    else:
        resp["progress_percent"] = 0 if job.status != "completed" else 100

    return resp

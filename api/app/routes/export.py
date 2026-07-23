"""Data export endpoints — GDPR-compliant full data download."""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
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
        resp["download_url"] = f"/api/v1/export/{job.id}/download"
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


@router.get("/{job_id}/download")
async def download_export(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the completed export ZIP.

    Owner-scoped: the job row is looked up with ExportJob.identity_id ==
    caller, exactly like the status route — another user's job_id 404s.

    This is the target of the download_url returned by
    GET /api/v1/export/{job_id}. The ZIP lives under a provider key with
    slashes ({identity}/system/export/...), which can never match the
    single-segment /api/v1/storage/files/{file_id} route (and no
    FileRecord is registered for it, deliberately: a FileRecord would
    count the ZIP against the user's storage quota and pull it into the
    next export), so the export job gets its own download endpoint.
    """
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.identity_id == user.identity_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    if job.status != "completed" or not job.download_key:
        raise HTTPException(status_code=409, detail="Export is not ready for download")

    if job.expires_at is not None:
        expires_at = job.expires_at
        if expires_at.tzinfo is None:
            # SQLite round-trips DateTime(timezone=True) as naive UTC.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Export download has expired")

    provider = _get_provider()
    try:
        data, content_type = await provider.download(job.download_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Export file not found in storage")
    except Exception:
        logger.exception("Export download failed for key %s", job.download_key)
        raise HTTPException(status_code=502, detail="Storage backend error")

    # job.id is a server-generated UUID string — safe for the header.
    return Response(
        content=data,
        media_type=content_type or "application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="windy-cloud-export-{job.id[:8]}.zip"'),
        },
    )

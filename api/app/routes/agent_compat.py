"""Agent-compat aliases (Wave 7 G16).

Pre-G16 the whole `storage_router` was mounted twice — once at the
canonical `/api/v1/storage/*` and again at `/api/v1/*`. That second
mount exposed `/api/v1/upload`, `/files`, `/files/{id}`, `/usage`,
`/export`, `/breakdown`, `/plans`, `/health` as a shadow API. Only
`/api/v1/files` was actually consumed — by windy-agent's ecosystem
health check — but every gate added to the `/storage/` prefix had to
remember the mirrors.

This module exposes the single endpoint windy-agent actually calls,
as a thin proxy to the real handler so every dep/gate applies
uniformly. Anything else the agent-compat mirror used to serve is
gone. If a new agent-compat alias is needed, add a named route here
rather than re-mounting the whole router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.db.engine import get_db
from api.app.models.storage import FileListResponse
from api.app.routes.storage import list_files

router = APIRouter()


@router.get("/files", response_model=FileListResponse, include_in_schema=False)
async def list_files_alias(
    product: str | None = Query(None),
    file_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Alias for `GET /api/v1/storage/files` — used by windy-agent's
    ecosystem-health probe. Delegates to the real handler so any gates
    added to the canonical route (e.g. the G1 frozen-account check)
    apply here too."""
    return await list_files(
        product=product,
        file_type=file_type,
        limit=limit,
        offset=offset,
        user=user,
        db=db,
    )

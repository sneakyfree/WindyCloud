"""Passport ↔ Windy identity bridge routes (Wave 2 contract #3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.webhook import verify_service_token
from api.app.db.engine import get_db
from api.app.db.models import IdentityBridge
from api.app.routes.webhooks import _link_passport
from api.app.utils.passport import is_valid_passport_number, validate_passport_number

router = APIRouter()


class LinkPassportRequest(BaseModel):
    windy_identity_id: str
    passport_number: str
    operator_email: str | None = None
    linked_by: str | None = None

    @field_validator("passport_number")
    @classmethod
    def _check_passport(cls, v: str) -> str:
        if not is_valid_passport_number(v):
            raise ValueError("Invalid passport_number format")
        return v


class BridgeResponse(BaseModel):
    windy_identity_id: str
    passport_number: str
    operator_email: str | None = None
    linked_by: str | None = None


@router.post(
    "/link-passport",
    response_model=BridgeResponse,
    dependencies=[Depends(verify_service_token)],
)
async def link_passport(
    body: LinkPassportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Upsert the passport ↔ identity bridge.

    Called by windy-agent after hatch, and by account-server when a human
    claims an existing passport. Idempotent on windy_identity_id.
    """
    row = await _link_passport(
        db,
        windy_identity_id=body.windy_identity_id,
        passport_number=body.passport_number,
        operator_email=body.operator_email,
        linked_by=body.linked_by,
    )
    return BridgeResponse(
        windy_identity_id=row.windy_identity_id,
        passport_number=row.passport_number,
        operator_email=row.operator_email,
        linked_by=row.linked_by,
    )


@router.get(
    "/by-passport/{passport_number}",
    response_model=BridgeResponse,
    dependencies=[Depends(verify_service_token)],
)
async def identity_by_passport(
    passport_number: str,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a passport number to the Windy identity it belongs to."""
    validate_passport_number(passport_number)
    result = await db.execute(
        select(IdentityBridge).where(IdentityBridge.passport_number == passport_number)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No identity for passport")
    return BridgeResponse(
        windy_identity_id=row.windy_identity_id,
        passport_number=row.passport_number,
        operator_email=row.operator_email,
        linked_by=row.linked_by,
    )

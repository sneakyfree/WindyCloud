"""VPS server endpoints — create, list, get, action, delete, plans."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import ServerRecord
from api.app.models.server import (
    ActionResult,
    PlansResponse,
    ServerActionRequest,
    ServerCreateRequest,
    ServerCreateResponse,
    ServerDeleteResponse,
    ServerInstance,
    ServerListResponse,
    ServerPlan,
)

router = APIRouter()


def _get_provider():
    if not settings.aws_access_key_id:
        return None
    from api.app.providers.aws_ec2 import AWSEC2Provider

    return AWSEC2Provider()


def _plans_from_provider():
    """Return plan list — works even without AWS credentials."""
    from api.app.providers.aws_ec2 import PLANS

    return [
        ServerPlan(plan_id=pid, **{k: v for k, v in p.items() if k != "instance_type"})
        for pid, p in PLANS.items()
    ]


@router.get("/plans", response_model=PlansResponse)
async def list_plans():
    return PlansResponse(plans=_plans_from_provider())


@router.post("/create", response_model=ServerCreateResponse)
async def create_server(
    body: ServerCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    provider = _get_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPS provisioning is not configured. Set AWS credentials.",
        )

    # Validate plan
    plans = {p.plan_id: p for p in _plans_from_provider()}
    if body.plan not in plans:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    plan_info = plans[body.plan]

    try:
        result = await provider.create(
            identity_id=user.identity_id,
            plan=body.plan,
            region=body.region,
            image=body.image,
            hostname=body.hostname,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    record = ServerRecord(
        identity_id=user.identity_id,
        plan_id=body.plan,
        region=body.region,
        image=body.image,
        status=result["status"],
        provider_instance_id=result.get("provider_instance_id"),
        ip_address=result.get("ip_address"),
        hostname=body.hostname,
        monthly_cost_cents=plan_info.price_cents_per_month,
    )
    db.add(record)
    await db.commit()

    return ServerCreateResponse(
        server_id=record.id,
        status=record.status,
    )


@router.get("", response_model=ServerListResponse)
async def list_servers(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ServerRecord)
        .where(
            ServerRecord.identity_id == user.identity_id,
            ServerRecord.status != "terminated",
        )
        .order_by(ServerRecord.created_at.desc())
    )
    records = result.scalars().all()

    servers = [
        ServerInstance(
            server_id=r.id,
            identity_id=r.identity_id,
            plan_id=r.plan_id,
            region=r.region,
            image=r.image,
            status=r.status,
            ip_address=r.ip_address,
            hostname=r.hostname,
            created_at=r.created_at,
            monthly_cost_cents=r.monthly_cost_cents,
        )
        for r in records
    ]
    return ServerListResponse(servers=servers, total=len(servers))


@router.get("/{server_id}", response_model=ServerInstance)
async def get_server(
    server_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ServerRecord).where(
            ServerRecord.id == server_id,
            ServerRecord.identity_id == user.identity_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Server not found")

    # Refresh status from provider if available
    provider = _get_provider()
    if provider and record.provider_instance_id:
        live = await provider.get(record.provider_instance_id)
        if live["status"] != "unknown":
            record.status = live["status"]
            record.ip_address = live.get("ip_address") or record.ip_address
            await db.commit()

    return ServerInstance(
        server_id=record.id,
        identity_id=record.identity_id,
        plan_id=record.plan_id,
        region=record.region,
        image=record.image,
        status=record.status,
        ip_address=record.ip_address,
        hostname=record.hostname,
        created_at=record.created_at,
        monthly_cost_cents=record.monthly_cost_cents,
    )


@router.post("/{server_id}/action", response_model=ActionResult)
async def server_action(
    server_id: str,
    body: ServerActionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.action not in ("start", "stop", "reboot"):
        raise HTTPException(status_code=400, detail="Action must be start, stop, or reboot")

    result = await db.execute(
        select(ServerRecord).where(
            ServerRecord.id == server_id,
            ServerRecord.identity_id == user.identity_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Server not found")

    provider = _get_provider()
    if provider is None or not record.provider_instance_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPS provider not available",
        )

    try:
        action_result = await provider.action(record.provider_instance_id, body.action)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    record.status = action_result["status"]
    await db.commit()

    return ActionResult(
        server_id=server_id,
        action=body.action,
        status=action_result["status"],
        message=action_result["message"],
    )


@router.delete("/{server_id}", response_model=ServerDeleteResponse)
async def delete_server(
    server_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ServerRecord).where(
            ServerRecord.id == server_id,
            ServerRecord.identity_id == user.identity_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Server not found")

    provider = _get_provider()
    if provider and record.provider_instance_id:
        await provider.delete(record.provider_instance_id)

    record.status = "terminated"
    record.terminated_at = datetime.now(timezone.utc)
    await db.commit()

    return ServerDeleteResponse(server_id=server_id, deleted=True)

"""HMAC webhook verification + service-token dependency.

Mirrors the pattern used in windy-mail's eternitas webhook handler
(api/app/services/eternitas.py:verify_webhook_signature) and the
service-token middleware (api/app/middleware/auth.py:verify_service_token).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import IdentityBridge, UserPlan


def verify_hmac_sha256(body: bytes, signature: str, secret: str) -> bool:
    """Timing-safe HMAC-SHA256 comparison.

    `signature` is expected to be the hex digest (no "sha256=" prefix).
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, sig)


async def verify_identity_webhook(
    request: Request,
    x_windy_signature: str = Header(..., alias="X-Windy-Signature"),
) -> bytes:
    """FastAPI dependency: verify HMAC on an identity-lifecycle webhook.

    Returns the raw body bytes so the route can parse them itself — this
    is required because signature verification must run over the exact
    bytes that were signed.
    """
    if not settings.identity_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )
    body = await request.body()
    if not verify_hmac_sha256(body, x_windy_signature, settings.identity_webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )
    return body


def verify_service_token(
    x_service_token: str = Header(..., alias="X-Service-Token"),
) -> bool:
    """FastAPI dependency: constant-time check against settings.service_token."""
    expected = settings.service_token or ""
    if not expected or not secrets.compare_digest(
        x_service_token.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )
    return True


async def get_user_or_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Auth dependency that accepts either a user JWT or a service token.

    Used by the archive-upload endpoints (all writes) → fails *closed*
    on trust-API unavailability so a suspended/revoked user can't slip
    through during an Eternitas outage.
    """
    service_token = request.headers.get("X-Service-Token")
    if service_token:
        expected = settings.service_token or ""
        if not expected or not secrets.compare_digest(
            service_token.encode(), expected.encode()
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid service token",
            )
        form = await request.form()
        identity_id = form.get("windy_identity_id")
        if not identity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Service-token callers must provide windy_identity_id",
            )
        user = AuthenticatedUser(
            identity_id=str(identity_id),
            claims={"sub": str(identity_id), "windy_identity_id": str(identity_id)},
            source="service",
        )
    else:
        # Re-use the normal Bearer flow
        from fastapi.security import HTTPBearer

        scheme = HTTPBearer()
        credentials = await scheme(request)
        user = await get_current_user(credentials)

    await _raise_if_blocked(db, user.identity_id, fail_closed_on_unavailable=True)
    return user


async def _raise_if_blocked(
    db: AsyncSession,
    identity_id: str,
    *,
    fail_closed_on_unavailable: bool = False,
) -> None:
    """Raise if the user's plan is frozen OR their passport is suspended/revoked.

    - frozen plan (set by the passport-revoked webhook) → 403 frozen_account
    - Eternitas Trust API reports status == "suspended"  → 403 suspended_account
    - Eternitas Trust API reports status == "revoked"    → 403 frozen_account

    `fail_closed_on_unavailable` controls what happens when the Trust API
    is unreachable and we have no cached answer (network / 5xx / timeout):

    - False (default, used on reads): fail open — let the request through
      so a degraded Eternitas doesn't black-hole normal user traffic.
    - True (used on writes/mutations): fail closed — return 503
      `trust_unavailable` so a user we can't verify can't perform a
      mutation we can't later roll back. GAP G8.

    Humans (no passport in the bridge) skip the trust call entirely on
    either path.
    """
    plan_row = await db.execute(select(UserPlan).where(UserPlan.identity_id == identity_id))
    plan = plan_row.scalar_one_or_none()
    if plan is not None and plan.frozen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="frozen_account",
        )

    bridge_row = await db.execute(
        select(IdentityBridge).where(IdentityBridge.windy_identity_id == identity_id)
    )
    bridge = bridge_row.scalar_one_or_none()
    if bridge is None:
        return  # human identity — skip trust

    from api.app.services.trust_client import get_trust_client

    trust = await get_trust_client().get_trust(bridge.passport_number)
    if trust is None:
        if fail_closed_on_unavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="trust_unavailable",
            )
        return  # read path — fail open
    if trust.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="frozen_account",
        )
    if trust.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="suspended_account",
        )


# Kept for backwards compat with any caller that imported the old name.
_raise_if_frozen = _raise_if_blocked


async def require_not_frozen(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Non-mutating read gate — fails *open* if the Trust API is unreachable.

    Use on list/download/export/breakdown endpoints so a degraded
    Eternitas doesn't black-hole normal reads. Writes should use
    `require_not_blocked_for_write` instead.
    """
    await _raise_if_blocked(db, user.identity_id)
    return user


async def require_not_blocked_for_write(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Mutation gate — fails *closed* if the Trust API is unreachable.

    Use on upload/delete/create endpoints where letting an unverifiable
    user mutate state during an Eternitas outage is worse than returning
    503 until trust recovers. GAP G8.
    """
    await _raise_if_blocked(db, user.identity_id, fail_closed_on_unavailable=True)
    return user


__all__ = [
    "get_user_or_service",
    "require_not_blocked_for_write",
    "require_not_frozen",
    "verify_hmac_sha256",
    "verify_identity_webhook",
    "verify_service_token",
]

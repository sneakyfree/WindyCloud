"""Auth passthrough for the Windy Cloud dashboard.

The dashboard used to ask people to paste a raw Windy Word JWT to sign in — a
developer-only affordance that a normal user can neither obtain nor understand.
This forwards an email + password to the Windy Pro account-server and returns
its token, so the dashboard can offer an ordinary sign-in while the browser
stays same-origin (no cross-site CORS to the account host).
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app.config import settings

router = APIRouter()


def _account_base() -> str:
    """Derive the account-server origin from the configured JWKS URL.

    e.g. ``https://account.windyword.ai/.well-known/jwks.json`` -> ``https://account.windyword.ai``
    """
    parsed = urlparse(settings.windy_pro_jwks_url)
    return f"{parsed.scheme}://{parsed.netloc}"


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Exchange email + password for a Windy identity token via the account-server."""
    target = f"{_account_base()}/api/v1/auth/login"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                target,
                json={"email": body.email, "password": body.password},
            )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="The account service is unreachable right now. Please try again in a moment.",
        )

    if resp.status_code == 200:
        # Pass the account-server payload straight through (token, refreshToken, name, tier, ...).
        return resp.json()
    if resp.status_code in (400, 401):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if resp.status_code == 403:
        # Correct credentials, but sign-in is blocked — almost always an
        # unverified email. Pass the 403 through with a human message instead
        # of collapsing it into a generic 502 (mirrors windy-mail #76). Before
        # this, a real unverified user saw "server error" instead of "verify
        # your email", and could never learn what to do.
        detail = "Please verify your email address to finish signing in."
        try:
            body = resp.json()
            reason = body.get("detail") or body.get("error") or body.get("message")
            if isinstance(reason, str) and reason and reason != "email_verification_required":
                detail = reason
        except Exception:
            pass
        raise HTTPException(status_code=403, detail=detail)
    raise HTTPException(status_code=502, detail="Sign-in failed. Please try again.")

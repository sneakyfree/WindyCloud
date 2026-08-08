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
from fastapi import APIRouter, HTTPException, Request
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


# ---------------------------------------------------------------------------
# Checkout passthrough
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    tier: str
    billing_type: str = "monthly"


@router.post("/checkout")
async def create_checkout(body: CheckoutRequest, request: Request):
    """Start a Stripe Checkout for a plan bought from the Windy Cloud console.

    Proxied to the account-server on purpose. There is ONE Stripe integration in
    the ecosystem and it lives there: one checkout, one webhook, one provisioner.
    This repo holds no Stripe key at all — a second implementation here would
    mean a second place that can create a subscription and a second place that
    can provision entitlements, which is exactly the split that let a Windy Word
    purchase provision nothing in Cloud for months.

    The caller's own bearer token is forwarded, so the account-server decides who
    the customer is; this route cannot be used to buy on someone else's behalf.
    """
    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Sign in to change your plan.")

    target = f"{_account_base()}/api/v1/stripe/create-checkout-session"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                target,
                json={
                    "tier": body.tier,
                    "billing_type": body.billing_type,
                    # Bought on the web, from the Cloud console — not the desktop
                    # app. `platform` is derived from the tier server-side and is
                    # deliberately NOT ours to assert.
                    "source": "web",
                    # Bring the buyer back HERE after Stripe, not to the Windy
                    # Word app. Set server-side (never from the client) and
                    # validated against an allowlist on the account-server side;
                    # older account-server builds simply ignore the field.
                    "return_to": "https://cloud.windycloud.com/billing",
                },
                headers={"Authorization": auth},
            )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="The account service is unreachable right now. Please try again in a moment.",
        )

    if resp.status_code == 200:
        return resp.json()
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Please sign in again to change your plan.")
    detail = "Could not start checkout."
    try:
        detail = resp.json().get("error") or detail
    except Exception:
        pass
    raise HTTPException(status_code=resp.status_code, detail=detail)

"""GAP G24: CORS is pinned to explicit methods/headers, not wildcards.

Wildcard allow_methods=["*"] + allow_headers=["*"] + allow_credentials=True
is a bad combination — browsers refuse the `Access-Control-Allow-Origin: *`
form with credentials, and Starlette special-cases this by echoing the
Origin header. The effective policy becomes "any origin we see in a
request can send credentials." This test pins the tightened config.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def cors_client(monkeypatch):
    from api.app.config import settings
    from api.app.main import create_app

    monkeypatch.setattr(settings, "cors_origins", "https://windyword.ai,https://windycloud.com")
    monkeypatch.setattr(settings, "dev_mode", False)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_preflight_allowed_origin_allowed_method(cors_client):
    resp = await cors_client.options(
        "/api/v1/storage/files",
        headers={
            "Origin": "https://windyword.ai",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert resp.status_code == 200
    # Must NOT use `*` — must echo the specific origin.
    assert resp.headers.get("access-control-allow-origin") == "https://windyword.ai"
    # Must include credentials flag for the allowed origin.
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_preflight_unknown_origin_not_allowed(cors_client):
    resp = await cors_client.options(
        "/api/v1/storage/files",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # Starlette CORSMiddleware returns 400 when the origin is disallowed
    # (it still responds, just without the allow-origin header set to
    # that origin). The exact status is either 400 or the preflight
    # simply lacks the ACAO header — both acceptable.
    if resp.status_code == 200:
        assert resp.headers.get("access-control-allow-origin") != "https://attacker.example"
    else:
        assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_preflight_disallowed_method_rejected(cors_client):
    resp = await cors_client.options(
        "/api/v1/storage/files",
        headers={
            "Origin": "https://windyword.ai",
            "Access-Control-Request-Method": "TRACE",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # TRACE isn't in our allow list; preflight should fail.
    if resp.status_code == 200:
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "TRACE" not in allowed
    else:
        assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_preflight_disallowed_header_rejected(cors_client):
    resp = await cors_client.options(
        "/api/v1/storage/files",
        headers={
            "Origin": "https://windyword.ai",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Sneaky-Header",
        },
    )
    if resp.status_code == 200:
        allowed = resp.headers.get("access-control-allow-headers", "").lower()
        assert "x-sneaky-header" not in allowed
    else:
        assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_service_token_header_is_allowed(cors_client):
    """X-Service-Token is on our explicit allow list so product backends
    can CORS-call the archive endpoints from a browser-like client."""
    resp = await cors_client.options(
        "/api/v1/archive/chat",
        headers={
            "Origin": "https://windyword.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Service-Token, Content-Type",
        },
    )
    assert resp.status_code == 200
    allowed_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "x-service-token" in allowed_headers

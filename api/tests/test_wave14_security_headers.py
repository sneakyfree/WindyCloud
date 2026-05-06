"""Wave 14 P1 — security headers middleware.

Smoke report §10 flagged that prod Cloud responses carried no
Strict-Transport-Security, X-Content-Type-Options, X-Frame-Options,
Content-Security-Policy, Referrer-Policy, or Permissions-Policy. This
suite verifies the middleware stamps them on every response surface we
serve (JSON, HTML landing, auth-failures, 404s).
"""

from __future__ import annotations

import pytest

_EXPECTED_HEADERS = {
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Content-Security-Policy",
}


def _assert_all_present(headers):
    missing = [h for h in _EXPECTED_HEADERS if h not in headers]
    assert not missing, f"Missing security headers: {missing}"


@pytest.mark.asyncio
async def test_json_endpoint_has_all_security_headers(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    _assert_all_present(resp.headers)


@pytest.mark.asyncio
async def test_html_landing_has_all_security_headers(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    _assert_all_present(resp.headers)


@pytest.mark.asyncio
async def test_404_response_also_carries_security_headers(client):
    """Error responses are still browser-renderable — headers must apply."""
    resp = await client.get("/api/v1/definitely-not-a-real-route")
    assert resp.status_code == 404
    _assert_all_present(resp.headers)


@pytest.mark.asyncio
async def test_auth_failure_response_carries_security_headers():
    """401 responses come straight from FastAPI before most routes run.
    Verify the middleware still stamps them."""
    from httpx import ASGITransport, AsyncClient

    from api.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/storage/files")  # no bearer → 401
    assert resp.status_code == 401
    _assert_all_present(resp.headers)


@pytest.mark.asyncio
async def test_hsts_value_is_reasonable(client):
    resp = await client.get("/health")
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]


@pytest.mark.asyncio
async def test_frame_ancestors_denies_embedding(client):
    resp = await client.get("/health")
    csp = resp.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert resp.headers["X-Frame-Options"] == "DENY"


@pytest.mark.asyncio
async def test_content_type_options_nosniff(client):
    resp = await client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_csp_blocks_inline_script(client):
    """We explicitly enumerate script-src 'self' (no 'unsafe-inline').
    The landing page's inline <style> needs 'unsafe-inline' on style-src
    but scripts must stay external-only."""
    resp = await client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


# ---------------------------------------------------------------------------
# CORS origins default (Wave 14 P1)
# ---------------------------------------------------------------------------


def test_cors_default_includes_apex_and_cloud_subdomain():
    """`config.Settings.cors_origins` default must cover the apex AND
    cloud subdomain so the running host picks up both even with no
    env override."""
    from api.app.config import Settings

    s = Settings(_env_file=None)  # ignore .env — exercise the default
    origins = s.cors_origins_list
    assert "https://cloud.windycloud.com" in origins
    assert "https://windyword.ai" in origins

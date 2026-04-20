"""Wave 14 P1 — analytics endpoints gated on require_admin.

Smoke report §8 flagged that `/api/v1/analytics/{daily,summary}` returned
fleet-wide aggregates to any authed user. This suite locks that down.
"""

from __future__ import annotations

import pytest

from api.app.auth.dependencies import (
    AuthenticatedUser,
    get_current_user,
    require_admin,
)
from api.app.config import settings


def _user(identity_id: str, **claims) -> AuthenticatedUser:
    base = {"sub": identity_id, "windy_identity_id": identity_id}
    base.update(claims)
    return AuthenticatedUser(identity_id=identity_id, claims=base, source="windy_pro")


@pytest.fixture
def admin_by_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "admin_identity_ids", "ops-grant,ops-second")
    return _user("ops-grant")


@pytest.fixture
def admin_by_scope():
    return _user("scope-admin", scopes=["windy_pro:*", "admin"])


@pytest.fixture
def admin_by_type():
    return _user("type-admin", type="admin")


@pytest.fixture
def non_admin():
    return _user("joe-public", scopes=["windy_pro:*"])


# ---------------------------------------------------------------------------
# require_admin unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_admin_accepts_allowlist_identity(admin_by_allowlist):
    result = await require_admin(user=admin_by_allowlist)
    assert result.identity_id == "ops-grant"


@pytest.mark.asyncio
async def test_require_admin_accepts_scope_admin(admin_by_scope):
    result = await require_admin(user=admin_by_scope)
    assert result.identity_id == "scope-admin"


@pytest.mark.asyncio
async def test_require_admin_accepts_scope_admin_oauth_string(monkeypatch):
    """Scopes emitted as a space-separated string (RFC 6749 §3.3)."""
    user = _user("oauth-admin", scopes="windy_pro:* windy_cloud:admin")
    result = await require_admin(user=user)
    assert result.identity_id == "oauth-admin"


@pytest.mark.asyncio
async def test_require_admin_accepts_type_admin(admin_by_type):
    result = await require_admin(user=admin_by_type)
    assert result.identity_id == "type-admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin(non_admin):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_admin(user=non_admin)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_rejects_empty_allowlist_and_no_scope(monkeypatch):
    monkeypatch.setattr(settings, "admin_identity_ids", "")
    user = _user("nobody")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_admin(user=user)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# HTTP integration: /api/v1/analytics/* gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_daily_rejects_non_admin(client):
    """The default `client` fixture's TEST_USER has no admin scope; the
    gate should 403. We do this by dropping the require_admin override
    the fixture sets — the default conftest overrides `get_current_user`
    to return TEST_USER, but not `require_admin`, so require_admin's
    inner get_current_user lookup will use the override. Since TEST_USER
    is not in any admin set, require_admin raises."""
    from api.app.main import create_app

    # Reuse the shared client fixture's app but clear admin allowlist so
    # TEST_USER can't slip through by env var.
    settings.admin_identity_ids = ""
    resp = await client.get("/api/v1/analytics/daily")
    assert resp.status_code == 403
    assert "Admin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_analytics_summary_rejects_non_admin(client):
    settings.admin_identity_ids = ""
    resp = await client.get("/api/v1/analytics/summary")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_analytics_daily_allows_allowlisted_admin(client, monkeypatch):
    """TEST_USER's identity_id is test-user-001; flipping that into the
    allowlist unlocks the endpoint."""
    monkeypatch.setattr(settings, "admin_identity_ids", "test-user-001")
    resp = await client.get("/api/v1/analytics/daily")
    assert resp.status_code == 200
    assert "days" in resp.json()


@pytest.mark.asyncio
async def test_analytics_summary_allows_allowlisted_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_identity_ids", "test-user-001")
    resp = await client.get("/api/v1/analytics/summary")
    assert resp.status_code == 200
    assert "total_files_uploaded" in resp.json()


@pytest.mark.asyncio
async def test_analytics_requires_bearer_at_all(client):
    """No auth at all must still 401, not 403, even after the admin
    gate. The gate sits *behind* get_current_user."""
    # The client fixture overrides get_current_user so we can't cleanly
    # strip it. Instead we hit the app directly without the override —
    # use a fresh app.
    from httpx import ASGITransport, AsyncClient

    from api.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/analytics/daily")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# admin_identity_ids_list parsing
# ---------------------------------------------------------------------------


def test_admin_identity_ids_list_handles_csv_spaces(monkeypatch):
    monkeypatch.setattr(settings, "admin_identity_ids", " a ,  b,c , ")
    assert settings.admin_identity_ids_list == ["a", "b", "c"]


def test_admin_identity_ids_list_empty():
    assert settings.admin_identity_ids_list == []

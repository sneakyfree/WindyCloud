"""EPT (Eternitas Passport Token) authentication tests.

Verifies that agents authenticated via Eternitas ES256 tokens
get mapped to their passport_number as identity.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.jwks import extract_identity_id


def test_extract_identity_windy_pro_token():
    """Windy Pro tokens use windy_identity_id claim."""
    claims = {"sub": "fallback-id", "windy_identity_id": "wid-12345"}
    assert extract_identity_id(claims) == "wid-12345"


def test_extract_identity_ept_passport():
    """EPT tokens use passport_number claim when windy_identity_id is absent."""
    claims = {"sub": "ET-00042", "passport_number": "ET-00042"}
    assert extract_identity_id(claims) == "ET-00042"


def test_extract_identity_sub_fallback():
    """Falls back to sub when no windy_identity_id or passport_number."""
    claims = {"sub": "generic-sub-id"}
    assert extract_identity_id(claims) == "generic-sub-id"


def test_extract_identity_priority():
    """windy_identity_id takes priority over passport_number."""
    claims = {
        "sub": "sub-id",
        "passport_number": "ET-00042",
        "windy_identity_id": "wid-99999",
    }
    assert extract_identity_id(claims) == "wid-99999"


@pytest.mark.asyncio
async def test_ept_authenticated_agent_uses_passport():
    """An agent with an EPT token should be identified by passport_number."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from api.app.config import settings
    from api.app.db.engine import get_db
    from api.app.db.models import Base
    from api.app.main import create_app

    # Create an EPT-style authenticated user (passport as identity)
    ept_user = AuthenticatedUser(
        identity_id="ET-00042",
        claims={"sub": "ET-00042", "passport_number": "ET-00042", "exp": 9999999999},
        source="eternitas",
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original = settings.use_mock_providers
    settings.use_mock_providers = True
    app = create_app()

    async def _override_user():
        return ept_user

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Upload a file as the EPT-authenticated agent
        resp = await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("agent.db", b"sqlite-backup-data", "application/x-sqlite3")},
            data={"product": "windy_fly", "file_type": "agent_backup"},
            headers={"Authorization": "Bearer ept-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "ET-00042" in body["key"]  # Key should contain passport number

        # List files — should only see this agent's files
        resp = await ac.get(
            "/api/v1/storage/files",
            headers={"Authorization": "Bearer ept-token"},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert len(files) == 1
        assert files[0]["product"] == "windy_fly"

    settings.use_mock_providers = original
    await engine.dispose()

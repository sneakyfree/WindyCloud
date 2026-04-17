"""Test fixtures — async test client with mocked auth."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.webhook import (
    get_user_or_service,
    require_not_blocked_for_write,
    require_not_frozen,
)
from api.app.db.engine import get_db
from api.app.db.models import Base

TEST_USER = AuthenticatedUser(
    identity_id="test-user-001",
    claims={"sub": "test-user-001", "windy_identity_id": "test-user-001"},
    source="windy_pro",
)


@pytest.fixture
async def db_session():
    """In-memory SQLite for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession):
    """Test client with mocked auth and in-memory DB."""
    from api.app.config import settings
    from api.app.main import create_app

    # Enable mock providers for testing
    original = settings.use_mock_providers
    settings.use_mock_providers = True

    app = create_app()

    async def _override_user():
        return TEST_USER

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_user_or_service] = _override_user
    app.dependency_overrides[require_not_frozen] = _override_user
    app.dependency_overrides[require_not_blocked_for_write] = _override_user
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    settings.use_mock_providers = original

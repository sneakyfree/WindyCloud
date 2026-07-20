"""Async GDPR export download tests (fix: undownloadable export link).

Regression coverage for the bug where the completed async export returned
``download_url = /api/v1/storage/files/export/{download_key}`` — a URL no
route matches (``download_key`` contains slashes, while the storage
download route takes a single-segment FileRecord UUID) — so every
completed export 404'd.

The fix serves the ZIP from ``GET /api/v1/export/{job_id}/download``,
gated on ``ExportJob.identity_id == caller``.

These tests build their own app/client instead of reusing conftest's
``client`` fixture because they need two extras it can't provide:

- a ``StaticPool`` in-memory engine shared with the export module's
  ``async_session`` — the background ``_run_export`` task opens its own
  session, and with the default pool every connection would get its own
  private ``:memory:`` database; and
- a switchable current-user, so the cross-user denial can be asserted.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.webhook import (
    get_user_or_service,
    require_not_blocked_for_write,
    require_not_frozen,
)
from api.app.db.engine import get_db
from api.app.db.models import Base, ExportJob

AUTH = {"Authorization": "Bearer fake"}

USER_A = AuthenticatedUser(
    identity_id="export-user-a",
    claims={"sub": "export-user-a", "windy_identity_id": "export-user-a"},
    source="windy_pro",
)
USER_B = AuthenticatedUser(
    identity_id="export-user-b",
    claims={"sub": "export-user-b", "windy_identity_id": "export-user-b"},
    source="windy_pro",
)


@pytest.fixture
async def export_env(monkeypatch):
    from api.app.config import settings
    from api.app.main import create_app
    from api.app.routes import export as export_routes

    # One shared connection so the export module's own session (opened via
    # its module-global `async_session`) sees the same in-memory DB as the
    # request sessions.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(export_routes, "async_session", session_factory)

    # Keep the real _run_export callable, but stub the module attribute so
    # the POST route's fire-and-forget `asyncio.create_task(_run_export(...))`
    # copy doesn't race the test — the tests drive the export to completion
    # deterministically by awaiting the saved original.
    real_run_export = export_routes._run_export

    async def _noop_run_export(job_id: str, identity_id: str) -> None:
        return None

    monkeypatch.setattr(export_routes, "_run_export", _noop_run_export)

    original_mock = settings.use_mock_providers
    settings.use_mock_providers = True

    app = create_app()
    current = {"user": USER_A}

    async def _override_user():
        return current["user"]

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_user_or_service] = _override_user
    app.dependency_overrides[require_not_frozen] = _override_user
    app.dependency_overrides[require_not_blocked_for_write] = _override_user
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield SimpleNamespace(
            client=ac,
            run_export=real_run_export,
            current=current,
            session_factory=session_factory,
        )

    settings.use_mock_providers = original_mock
    await engine.dispose()


async def _complete_export(env) -> tuple[str, str]:
    """Upload a file, request the async export, run it to completion.

    Returns (job_id, download_url) from the completed status response.
    """
    resp = await env.client.post(
        "/api/v1/storage/upload",
        files={"file": ("hello.txt", b"export me", "text/plain")},
        data={"product": "windy_pro", "file_type": "recording"},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text

    resp = await env.client.post("/api/v1/export/my-data", headers=AUTH)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # Deterministically run the (stubbed-out) background task to completion.
    await env.run_export(job_id, env.current["user"].identity_id)

    resp = await env.client.get(f"/api/v1/export/{job_id}", headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed", body
    assert "download_url" in body, body
    return job_id, body["download_url"]


@pytest.mark.asyncio
async def test_completed_export_download_url_resolves(export_env):
    """The download_url of a completed async export must actually download.

    Regression: it used to be /api/v1/storage/files/export/{download_key},
    which no route matches (the key contains slashes) — a guaranteed 404.
    """
    job_id, url = await _complete_export(export_env)

    # Must point at the job-scoped download route (single resolvable path).
    assert url == f"/api/v1/export/{job_id}/download"

    resp = await export_env.client.get(url, headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/zip")
    assert "attachment" in resp.headers.get("content-disposition", "")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "windy_pro/recording/hello.txt" in zf.namelist()
        assert zf.read("windy_pro/recording/hello.txt") == b"export me"


@pytest.mark.asyncio
async def test_other_user_cannot_download_export(export_env):
    """Owner scoping: a different identity must not reach another's export."""
    job_id, url = await _complete_export(export_env)

    export_env.current["user"] = USER_B

    resp = await export_env.client.get(url, headers=AUTH)
    assert resp.status_code == 404

    # And user B can't see the job status either (same scoping).
    resp = await export_env.client.get(f"/api/v1/export/{job_id}", headers=AUTH)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_before_completion_is_409(export_env):
    """A pending job has no ZIP yet — download must refuse, not 500."""
    resp = await export_env.client.post("/api/v1/export/my-data", headers=AUTH)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    resp = await export_env.client.get(f"/api/v1/export/{job_id}/download", headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_expired_export_download_is_410(export_env):
    """Past expires_at the download link is dead (contract: 24h window)."""
    job_id, url = await _complete_export(export_env)

    async with export_env.session_factory() as session:
        job = await session.get(ExportJob, job_id)
        job.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await session.commit()

    resp = await export_env.client.get(url, headers=AUTH)
    assert resp.status_code == 410

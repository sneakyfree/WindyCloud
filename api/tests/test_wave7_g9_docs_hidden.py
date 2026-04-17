"""GAP G9: /docs, /redoc, /openapi.json must be hidden in production.

In dev mode they stay on for local exploration. In prod they 404 so the
full API surface (service-token endpoints + webhook shapes) isn't
publicly discoverable.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_docs_hidden_when_dev_mode_false(monkeypatch):
    from api.app.config import settings
    from api.app.main import create_app

    monkeypatch.setattr(settings, "dev_mode", False)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in ("/docs", "/redoc", "/openapi.json"):
            resp = await ac.get(path)
            assert resp.status_code == 404, (
                f"{path} must be hidden in prod (got {resp.status_code})"
            )


@pytest.mark.asyncio
async def test_docs_exposed_when_dev_mode_true(monkeypatch):
    from api.app.config import settings
    from api.app.main import create_app

    monkeypatch.setattr(settings, "dev_mode", True)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/docs")).status_code == 200
        assert (await ac.get("/openapi.json")).status_code == 200

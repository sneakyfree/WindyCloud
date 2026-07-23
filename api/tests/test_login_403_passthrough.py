"""Cloud login must pass the account-server's 403 through, not collapse it to 502.

SOTU-2 latent bug (same class as windy-mail #76): an unverified user has the
right password, so the account-server returns 403 email_verification_required —
but the Cloud login route mapped every non-{200,400,401} status to a generic
502 "Sign-in failed", so the user saw a server error instead of "verify your
email". This asserts the 403 (and a human message) now flows through.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._resp


@pytest.mark.asyncio
async def test_login_403_passes_through(monkeypatch):
    from api.app.main import create_app
    from api.app.routes import auth as auth_module

    fake = _FakeResp(403, {"detail": "email_verification_required"})
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda *a, **k: _FakeClient(fake))

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "pw"})

    assert resp.status_code == 403  # was 502 before the fix
    assert "verify" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_wrong_password_still_401(monkeypatch):
    from api.app.main import create_app
    from api.app.routes import auth as auth_module

    fake = _FakeResp(401, {"detail": "bad"})
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda *a, **k: _FakeClient(fake))

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "pw"})

    assert resp.status_code == 401

"""Paid GPU path fails CLOSED when the Trust API is unavailable.

POST /compute/stt spends real money (GPU minutes) but was gated with the
read-path `require_not_frozen` dep, which fails OPEN when Eternitas is
unreachable — so a suspended/revoked agent could burn compute during any
trust blip. The route now uses `require_not_blocked_for_write` (same as
servers.py POST /create): 503 `trust_unavailable` for a bot identity we
can't verify, while humans (no bridge row) skip trust entirely.

Setup mirrors test_wave7_g8_trust_fail_closed.py (trust-down stub) and
test_wave7_compute_frozen_gate.py (real-gate client for /compute/stt).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.db.models import IdentityBridge, UserPlan


class _TrustDown:
    """Trust client stub that always returns None (simulates Eternitas down)."""

    async def get_trust(self, passport: str):
        return None

    def invalidate(self, passport: str) -> None:
        pass


class _TrustActive:
    """Trust client stub that reports an active (not blocked) passport."""

    async def get_trust(self, passport: str):
        return SimpleNamespace(status="active")

    def invalidate(self, passport: str) -> None:
        pass


def _install_trust_stub(monkeypatch, stub):
    from api.app.auth import webhook as wh_mod
    from api.app.services import trust_client as tc_mod

    monkeypatch.setattr(tc_mod, "_trust_client", stub)
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: stub)
    monkeypatch.setattr(wh_mod, "_trust_client", stub, raising=False)
    return stub


@pytest.fixture
def trust_down(monkeypatch):
    return _install_trust_stub(monkeypatch, _TrustDown())


async def _real_gate_client(db_session, identity_id: str):
    """Build a client that uses the REAL trust-gate deps
    (conftest overrides them for convenience; we want the real gate)."""
    from api.app.auth.dependencies import AuthenticatedUser, get_current_user
    from api.app.db.engine import get_db
    from api.app.main import create_app

    app = create_app()

    async def _user():
        return AuthenticatedUser(
            identity_id=identity_id,
            claims={"sub": identity_id, "windy_identity_id": identity_id},
            source="windy_pro",
        )

    async def _db():
        yield db_session

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _post_stt(ac):
    return ac.post(
        "/api/v1/compute/stt",
        files={"file": ("a.opus", b"fake-audio", "audio/opus")},
        headers={"Authorization": "Bearer fake"},
    )


@pytest.mark.asyncio
async def test_stt_fails_closed_when_trust_unavailable(db_session, trust_down, monkeypatch):
    """Bot identity + Eternitas down → /compute/stt 503 trust_unavailable.

    This is the fix under test: previously the read gate let this request
    through (fail-open) and the GPU job ran.
    """
    from api.app.config import settings

    monkeypatch.setattr(settings, "use_mock_providers", True)

    db_session.add(IdentityBridge(windy_identity_id="bot-stt", passport_number="ET-BOT-STT"))
    db_session.add(
        UserPlan(
            identity_id="bot-stt",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "bot-stt") as ac:
        resp = await _post_stt(ac)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "trust_unavailable"


@pytest.mark.asyncio
async def test_human_stt_succeeds_when_trust_unavailable(db_session, trust_down, monkeypatch):
    """Human identity (no bridge row) skips trust entirely; Eternitas
    being down must not block a normal caller from /compute/stt."""
    from api.app.config import settings

    monkeypatch.setattr(settings, "use_mock_providers", True)

    db_session.add(
        UserPlan(
            identity_id="human-stt",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "human-stt") as ac:
        resp = await _post_stt(ac)
    # Must NOT be blocked by the trust gate. Happy path is 200 from the
    # mock provider; mirror test_wave7_compute_frozen_gate's tolerant
    # control assertion in case the mock provider isn't wired cleanly on
    # a branch — the key assertions are: no trust_unavailable, no 403.
    assert resp.json().get("detail") != "trust_unavailable"
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_active_bot_stt_passes_gate_when_trust_up(db_session, monkeypatch):
    """Control: a bot with an active passport is not blocked by the new
    write gate when Eternitas is reachable."""
    from api.app.config import settings

    _install_trust_stub(monkeypatch, _TrustActive())
    monkeypatch.setattr(settings, "use_mock_providers", True)

    db_session.add(IdentityBridge(windy_identity_id="bot-ok", passport_number="ET-BOT-OK"))
    db_session.add(
        UserPlan(
            identity_id="bot-ok",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "bot-ok") as ac:
        resp = await _post_stt(ac)
    assert resp.json().get("detail") != "trust_unavailable"
    assert resp.status_code != 403

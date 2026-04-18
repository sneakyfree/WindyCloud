"""GAP G8: mutations fail CLOSED when the Trust API is unavailable.

Reads still fail open (a degraded Eternitas must not black-hole normal
user traffic), but uploads / archive writes must 503 rather than let a
user we can't verify mutate state. The dedicated
`require_not_blocked_for_write` dep carries the fail-closed behaviour;
the existing `require_not_frozen` stays fail-open for reads.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.db.models import IdentityBridge, UserPlan


class _TrustDown:
    """Trust client stub that always returns None (simulates Eternitas down)."""

    async def get_trust(self, passport: str):
        return None

    def invalidate(self, passport: str) -> None:
        pass


@pytest.fixture
def trust_down(monkeypatch):
    from api.app.auth import webhook as wh_mod
    from api.app.services import trust_client as tc_mod

    stub = _TrustDown()
    monkeypatch.setattr(tc_mod, "_trust_client", stub)
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: stub)
    monkeypatch.setattr(wh_mod, "_trust_client", stub, raising=False)
    return stub


async def _real_gate_client(db_session, identity_id: str):
    """Build a client that uses the REAL require_not_*_for_write deps
    (conftest overrides them, so we rebuild the app ourselves)."""
    from api.app.auth.dependencies import AuthenticatedUser, get_current_user
    from api.app.db.engine import get_db
    from api.app.main import create_app

    app = create_app()

    async def _user():
        return AuthenticatedUser(
            identity_id=identity_id,
            claims={"sub": identity_id},
            source="windy_pro",
        )

    async def _db():
        yield db_session

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_upload_fails_closed_when_trust_unavailable(db_session, trust_down):
    """Bot identity + Eternitas down → upload 503 trust_unavailable."""
    db_session.add(IdentityBridge(windy_identity_id="bot-1", passport_number="ET-BOT-1"))
    db_session.add(
        UserPlan(
            identity_id="bot-1",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "bot-1") as ac:
        resp = await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("a.bin", b"ab", "application/octet-stream")},
            data={"metadata": json.dumps({})},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "trust_unavailable"


@pytest.mark.asyncio
async def test_human_upload_succeeds_when_trust_unavailable(db_session, trust_down):
    """Human identity (no bridge row) skips trust entirely; Eternitas
    being down is invisible to them."""
    db_session.add(
        UserPlan(
            identity_id="human-1",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "human-1") as ac:
        resp = await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("a.bin", b"ab", "application/octet-stream")},
            data={"metadata": json.dumps({})},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_read_gate_still_fails_open_when_trust_unavailable(db_session, trust_down):
    """The read-path dep must *not* change behaviour from G8.

    Direct call to _raise_if_blocked without fail_closed — a bot whose
    passport can't be verified should fall through without raising.
    """
    db_session.add(IdentityBridge(windy_identity_id="bot-r", passport_number="ET-BOT-R"))
    db_session.add(
        UserPlan(
            identity_id="bot-r",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    from api.app.auth.webhook import _raise_if_blocked

    # Reads: default (fail_closed_on_unavailable=False) — must NOT raise.
    await _raise_if_blocked(db_session, "bot-r")

    # Writes: fail_closed=True — must raise 503 trust_unavailable.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _raise_if_blocked(db_session, "bot-r", fail_closed_on_unavailable=True)
    assert exc.value.status_code == 503
    assert exc.value.detail == "trust_unavailable"

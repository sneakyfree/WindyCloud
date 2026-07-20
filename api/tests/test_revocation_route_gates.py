"""Live revocation on every user-facing route (auth-scope workstream).

Before this change, servers list/get/action/delete, billing reads + sync,
sync status/offer-backup, compute GETs, and the agent /files alias sat on
bare `get_current_user` — no frozen check, no live Eternitas status check.
A revoked agent kept using them all until its JWT expired.

Now every user-facing route carries a trust gate:
  reads  → require_not_frozen           (rejects revoked/suspended live;
                                         fail-OPEN if Eternitas is down)
  writes → require_not_blocked_for_write (same, but fail-CLOSED 503)

Same harness as test_wave7_g8_trust_fail_closed.py: rebuild the app with
the REAL gate deps (conftest normally overrides them), stub the trust
client, and drive real HTTP.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.db.models import IdentityBridge, UserPlan
from api.app.services.trust_client import TrustInfo


class _TrustRevoked:
    """Trust client stub: passport exists but is revoked."""

    async def get_trust(self, passport: str):
        return TrustInfo(
            passport_number=passport,
            status="revoked",
            tier_multiplier=0.0,
            band="critical",
            allowed_actions=(),
        )

    def invalidate(self, passport: str) -> None:
        pass


class _TrustDown:
    """Trust client stub: Eternitas unreachable."""

    async def get_trust(self, passport: str):
        return None

    def invalidate(self, passport: str) -> None:
        pass


def _install_trust_stub(monkeypatch, stub):
    from api.app.auth import webhook as wh_mod
    from api.app.services import trust_client as tc_mod

    monkeypatch.setattr(tc_mod, "_trust_client", stub)
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: stub)
    monkeypatch.setattr(wh_mod, "_trust_client", stub, raising=False)


async def _real_gate_client(db_session, identity_id: str):
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


async def _seed_bot(db_session, identity_id: str, passport: str):
    db_session.add(IdentityBridge(windy_identity_id=identity_id, passport_number=passport))
    db_session.add(
        UserPlan(
            identity_id=identity_id,
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()


HDRS = {"Authorization": "Bearer x"}

# (method, path, kwargs) — routes that were bare get_current_user before.
READ_ROUTES = [
    ("GET", "/api/v1/servers", {}),
    ("GET", "/api/v1/billing/usage", {}),
    ("GET", "/api/v1/billing/plan", {}),
    ("GET", "/api/v1/compute/usage", {}),
    ("GET", "/api/v1/sync/status", {}),
    ("GET", "/api/v1/files", {}),
]
WRITE_ROUTES = [
    ("POST", "/api/v1/servers/srv-x/action", {"json": {"action": "stop"}}),
    ("DELETE", "/api/v1/servers/srv-x", {}),
    ("POST", "/api/v1/sync/offer-backup", {"json": {"recording_count": 3}}),
]


@pytest.mark.asyncio
async def test_revoked_bot_is_rejected_on_reads_and_writes(db_session, monkeypatch):
    """A revoked passport gets 403 on EVERY formerly-bare route, live."""
    _install_trust_stub(monkeypatch, _TrustRevoked())
    await _seed_bot(db_session, "bot-rvk", "ET-BOT-RVK")

    async with await _real_gate_client(db_session, "bot-rvk") as ac:
        for method, path, kw in READ_ROUTES + WRITE_ROUTES:
            resp = await ac.request(method, path, headers=HDRS, **kw)
            assert resp.status_code == 403, (method, path, resp.status_code, resp.text)
            assert resp.json()["detail"] == "frozen_account", (method, path)


@pytest.mark.asyncio
async def test_outage_reads_fail_open_writes_fail_closed(db_session, monkeypatch):
    """Eternitas down: reads still work (fail-open), writes 503 (fail-closed)."""
    _install_trust_stub(monkeypatch, _TrustDown())
    await _seed_bot(db_session, "bot-dwn", "ET-BOT-DWN")

    async with await _real_gate_client(db_session, "bot-dwn") as ac:
        for method, path, kw in READ_ROUTES:
            resp = await ac.request(method, path, headers=HDRS, **kw)
            assert resp.status_code != 403 and resp.status_code != 503, (
                method, path, resp.status_code, resp.text,
            )
        for method, path, kw in WRITE_ROUTES:
            resp = await ac.request(method, path, headers=HDRS, **kw)
            assert resp.status_code == 503, (method, path, resp.status_code, resp.text)
            assert resp.json()["detail"] == "trust_unavailable", (method, path)


@pytest.mark.asyncio
async def test_human_is_unaffected_even_during_outage(db_session, monkeypatch):
    """No IdentityBridge row = human: trust is never consulted, reads and
    writes behave exactly as before (404s for unknown server are fine —
    the point is no 403/503 from the gate)."""
    _install_trust_stub(monkeypatch, _TrustDown())
    db_session.add(
        UserPlan(
            identity_id="human-x",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()

    async with await _real_gate_client(db_session, "human-x") as ac:
        for method, path, kw in READ_ROUTES + WRITE_ROUTES:
            resp = await ac.request(method, path, headers=HDRS, **kw)
            assert resp.status_code not in (403, 503), (
                method, path, resp.status_code, resp.text,
            )

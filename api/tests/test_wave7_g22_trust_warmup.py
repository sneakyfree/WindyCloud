"""GAP G22: trust cache warmup pre-fetches known passports at startup.

Pre-G22 a fresh Fargate task cold-started with an empty trust cache,
so the first upload-gate call per-passport hit Eternitas synchronously.
Under G8's fail-closed write gate that turns every first-post-deploy
write into a 503 if the trust round-trip times out.

warmup_trust_cache reads the bridge table and pre-fetches trust for
each passport in a rate-limited trickle. Failures are logged, not
fatal.
"""

from __future__ import annotations

import pytest

from api.app.db.models import IdentityBridge
from api.app.tasks.trust_warmup import warmup_trust_cache


class _TrustStub:
    """Records which passports got fetched."""

    def __init__(self, returns=None, raises=None):
        self.calls = []
        self._returns = returns or {}
        self._raises = raises or set()

    async def get_trust(self, passport):
        self.calls.append(passport)
        if passport in self._raises:
            raise RuntimeError(f"boom on {passport}")
        return self._returns.get(passport)

    def invalidate(self, passport):
        pass


@pytest.fixture
def fast_warmup(monkeypatch):
    """Point the trust client at our stub and patch the warmup interval
    to 0 so tests don't actually sleep."""
    from api.app.services import trust_client as tc_mod
    from api.app.tasks import trust_warmup as warmup_mod

    stub = _TrustStub()
    monkeypatch.setattr(tc_mod, "_trust_client", stub)
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: stub)
    monkeypatch.setattr(warmup_mod, "_WARMUP_INTERVAL_SECONDS", 0.0)
    return stub


@pytest.mark.asyncio
async def test_empty_bridge_table_is_a_noop(db_session, fast_warmup):
    counters = await warmup_trust_cache(db_session)
    assert counters == {"attempted": 0, "ok": 0, "failed": 0}
    assert fast_warmup.calls == []


@pytest.mark.asyncio
async def test_warmup_fetches_every_linked_passport(db_session, fast_warmup):
    from api.app.services.trust_client import TrustInfo

    # Seed bridge rows
    for i in range(5):
        db_session.add(
            IdentityBridge(
                windy_identity_id=f"g22-id-{i}",
                passport_number=f"ET-G22-{i}",
            )
        )
    await db_session.commit()

    # Stub returns a TrustInfo for 3 of them, None for 2
    for i in (0, 1, 3):
        fast_warmup._returns[f"ET-G22-{i}"] = TrustInfo(
            passport_number=f"ET-G22-{i}",
            status="active",
            tier_multiplier=1.0,
        )

    counters = await warmup_trust_cache(db_session, interval=0.0)
    assert counters["attempted"] == 5
    assert counters["ok"] == 3
    assert counters["failed"] == 0
    # All passports were asked for
    assert set(fast_warmup.calls) == {f"ET-G22-{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_warmup_tolerates_individual_failures(db_session, fast_warmup):
    """A failing passport fetch doesn't abort the whole warmup."""
    for pn in ("ET-OK-A", "ET-BREAK", "ET-OK-B"):
        db_session.add(
            IdentityBridge(
                windy_identity_id=f"id-{pn}",
                passport_number=pn,
            )
        )
    await db_session.commit()

    fast_warmup._raises.add("ET-BREAK")

    counters = await warmup_trust_cache(db_session, interval=0.0)
    assert counters["attempted"] == 3
    assert counters["failed"] == 1
    assert "ET-BREAK" in fast_warmup.calls
    # The other two still got fetched
    assert "ET-OK-A" in fast_warmup.calls
    assert "ET-OK-B" in fast_warmup.calls


@pytest.mark.asyncio
async def test_warmup_respects_max_passports_cap(db_session, fast_warmup):
    """max_passports is a hard cap so startup can't block on a huge bridge."""
    for i in range(20):
        db_session.add(
            IdentityBridge(
                windy_identity_id=f"cap-{i}",
                passport_number=f"ET-CAP-{i:03d}",
            )
        )
    await db_session.commit()

    counters = await warmup_trust_cache(db_session, interval=0.0, max_passports=5)
    assert counters["attempted"] == 5
    assert len(fast_warmup.calls) == 5

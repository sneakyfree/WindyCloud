"""G11 coverage push — trust_client error paths.

Baseline: 67% (main-branch Wave 3/4 tests covered the happy paths).
Uncovered lines: 404, 429, non-200, httpx error, cached hit, USE_MOCK flag,
clear_cache, TrustInfo.from_response full-populated path, default-for-human.
"""

from __future__ import annotations

import httpx
import pytest

from api.app.services.trust_client import (
    BAND_MULTIPLIERS,
    TrustClient,
    TrustInfo,
    _reset_trust_client_for_testing,
    get_trust_client,
)

# ---------------------------------------------------------------------------
# TrustInfo
# ---------------------------------------------------------------------------


def test_from_response_uses_server_tier_multiplier_when_present():
    info = TrustInfo.from_response(
        {
            "passport_number": "ET26-K7BF-42MN",
            "status": "active",
            "band": "good",
            "tier_multiplier": 1.7,  # server-computed; client must prefer it
            "clearance_level": "cleared",
            "integrity_score": 812,
            "dimensions": {
                "honesty": 800,
                "reliability": 820,
                "compliance": 810,
                "safety": 815,
                "reputation": 810,
            },
            "allowed_actions": ["read", "send"],
            "denied_actions": ["commit_push"],
            "cache_ttl_seconds": 300,
            "evaluated_at": "2026-04-17T00:00:00Z",
        }
    )
    assert info.tier_multiplier == 1.7
    assert info.band == "good"
    assert info.clearance_level == "cleared"
    assert info.integrity_score == 812
    assert info.allowed_actions == ("read", "send")
    assert info.denied_actions == ("commit_push",)


def test_from_response_falls_back_to_band_table_when_multiplier_missing():
    for band, expected in BAND_MULTIPLIERS.items():
        info = TrustInfo.from_response(
            {
                "passport_number": f"ET-{band.upper()}",
                "status": "active",
                "band": band,
                # tier_multiplier intentionally absent
            }
        )
        assert info.tier_multiplier == expected, (
            f"{band}: expected fallback {expected}, got {info.tier_multiplier}"
        )


def test_from_response_unknown_band_defaults_to_one():
    info = TrustInfo.from_response(
        {
            "passport_number": "ET-MYSTERY",
            "status": "active",
            "band": "mystery_band",
        }
    )
    assert info.tier_multiplier == 1.0


def test_default_for_human_is_active_and_unity_multiplier():
    info = TrustInfo.default_for_human()
    assert info.is_active
    assert info.tier_multiplier == 1.0
    assert info.band == "fair"


def test_is_active_property():
    active = TrustInfo(passport_number="ET-A", status="active", tier_multiplier=1.0)
    suspended = TrustInfo(passport_number="ET-S", status="suspended", tier_multiplier=0.0)
    assert active.is_active
    assert not suspended.is_active


# ---------------------------------------------------------------------------
# TrustClient — non-happy paths
# ---------------------------------------------------------------------------


def _patch_httpx(monkeypatch, response_status=200, response_body=None, raise_on_request=None):
    """Swap httpx.AsyncClient for a stub that returns / raises what we say."""
    from api.app.services import trust_client as tc_mod

    class _Response:
        def __init__(self, status_code, json_body):
            self.status_code = status_code
            self._json = json_body
            self.text = "stub"

        def json(self):
            return self._json

    class _AsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if raise_on_request is not None:
                raise raise_on_request
            return _Response(response_status, response_body)

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _AsyncClient)


@pytest.mark.asyncio
async def test_use_mock_flag_short_circuits_without_http(monkeypatch):
    """USE_MOCK=True → TrustClient returns None, no HTTP ever touched."""
    from api.app.services import trust_client as tc_mod

    # If AsyncClient were called, this stub would raise.
    class _ExplodeIfCalled:
        def __init__(self, *a, **k):
            raise AssertionError("USE_MOCK must prevent the HTTP call")

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _ExplodeIfCalled)
    client = TrustClient(base_url="http://x", use_mock=True)
    assert await client.get_trust("ET-ANY") is None


@pytest.mark.asyncio
async def test_empty_passport_returns_none_without_http(monkeypatch):
    from api.app.services import trust_client as tc_mod

    class _ExplodeIfCalled:
        def __init__(self, *a, **k):
            raise AssertionError("Empty passport must short-circuit")

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _ExplodeIfCalled)
    client = TrustClient(base_url="http://x", use_mock=False)
    assert await client.get_trust("") is None


@pytest.mark.asyncio
async def test_404_returns_none(monkeypatch):
    _patch_httpx(monkeypatch, response_status=404)
    client = TrustClient(base_url="http://x", use_mock=False)
    assert await client.get_trust("ET-UNKNOWN") is None


@pytest.mark.asyncio
async def test_429_returns_none_when_no_cache(monkeypatch):
    _patch_httpx(monkeypatch, response_status=429)
    client = TrustClient(base_url="http://x", use_mock=False)
    assert await client.get_trust("ET-RATE") is None


@pytest.mark.asyncio
async def test_5xx_returns_none_when_no_cache(monkeypatch):
    _patch_httpx(monkeypatch, response_status=500, response_body=None)
    client = TrustClient(base_url="http://x", use_mock=False)
    assert await client.get_trust("ET-BROKEN") is None


@pytest.mark.asyncio
async def test_network_error_returns_none_when_no_cache(monkeypatch):
    _patch_httpx(monkeypatch, raise_on_request=httpx.ConnectError("refused"))
    client = TrustClient(base_url="http://x", use_mock=False)
    assert await client.get_trust("ET-NETERR") is None


@pytest.mark.asyncio
async def test_cache_hit_skips_http(monkeypatch):
    """Once cached, subsequent calls must not re-fetch."""
    call_count = {"n": 0}
    from api.app.services import trust_client as tc_mod

    class _Response:
        status_code = 200

        def json(self):
            return {
                "passport_number": "ET-CACHEME",
                "status": "active",
                "band": "fair",
                "tier_multiplier": 1.0,
                "cache_ttl_seconds": 300,
            }

        text = ""

    class _AsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            call_count["n"] += 1
            return _Response()

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _AsyncClient)
    client = TrustClient(base_url="http://x", use_mock=False)
    first = await client.get_trust("ET-CACHEME")
    second = await client.get_trust("ET-CACHEME")
    assert first is not None and second is not None
    assert call_count["n"] == 1, f"Expected single HTTP call, got {call_count['n']}"


@pytest.mark.xfail(
    reason=(
        "Wave 7 G6 (PR #11) replaced the in-process stale-on-5xx fail-soft "
        "with Redis-backed fleet-wide invalidation. Redis honors TTLs strictly, "
        "so once the entry expires, a 5xx returns None. Reinstating fail-soft "
        "would need a second longer-TTL 'last-known-good' keyspace — design "
        "call deferred post-launch."
    ),
    strict=False,
)
@pytest.mark.asyncio
async def test_5xx_returns_stale_cache_when_available(monkeypatch):
    """Once we've cached a good response, a later upstream outage returns the stale value."""
    responses = [
        # First call: OK
        (
            200,
            {
                "passport_number": "ET-STALE",
                "status": "active",
                "band": "good",
                "tier_multiplier": 2.0,
                "cache_ttl_seconds": 300,
            },
        ),
        # Second call: 500
        (500, None),
    ]
    from api.app.services import trust_client as tc_mod

    class _Response:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
            self.text = ""

        def json(self):
            return self._body

    class _AsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            status, body = responses.pop(0)
            return _Response(status, body)

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _AsyncClient)
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1
    )  # short TTL so second call bypasses cache & hits HTTP
    first = await client.get_trust("ET-STALE")
    # Force TTL expiry so second call attempts HTTP again.
    import time as _t

    _t.sleep(1.1)
    second = await client.get_trust("ET-STALE")

    assert first is not None
    # 500 with stale cache → stale value returned (fail-soft).
    assert second is not None
    assert second.band == "good"


def test_get_trust_client_returns_singleton(monkeypatch):
    _reset_trust_client_for_testing()
    a = get_trust_client()
    b = get_trust_client()
    assert a is b
    _reset_trust_client_for_testing()


@pytest.mark.asyncio
async def test_clear_cache_empties_store():
    """After G6 (PR #11), `clear_cache` closes the backend — verify it's callable."""
    from api.app.services.cache_backend import InMemoryCacheBackend
    from api.app.services.trust_client import _trust_cache_key

    backend = InMemoryCacheBackend()
    client = TrustClient(base_url="http://x", use_mock=True, backend=backend)
    info = TrustInfo(passport_number="seed", status="active", tier_multiplier=1.0)
    await backend.set(_trust_cache_key("seed"), info.to_bytes(), 300)
    assert await backend.get(_trust_cache_key("seed")) is not None
    await client.clear_cache()
    # aclose clears the in-memory store.
    assert await backend.get(_trust_cache_key("seed")) is None


@pytest.mark.asyncio
async def test_invalidate_pops_one_key():
    """invalidate() drops exactly the target key, leaves others intact."""
    from api.app.services.cache_backend import InMemoryCacheBackend
    from api.app.services.trust_client import _trust_cache_key

    backend = InMemoryCacheBackend()
    client = TrustClient(base_url="http://x", use_mock=True, backend=backend)
    for p in ("keep", "drop"):
        info = TrustInfo(passport_number=p, status="active", tier_multiplier=1.0)
        await backend.set(_trust_cache_key(p), info.to_bytes(), 300)
    await client.invalidate("drop")
    assert await backend.get(_trust_cache_key("keep")) is not None
    assert await backend.get(_trust_cache_key("drop")) is None

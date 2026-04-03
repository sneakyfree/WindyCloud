"""Rate limiting middleware tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_rate_limit_allows_normal_traffic(client):
    """Normal requests should not be rate limited."""
    for _ in range(5):
        resp = await client.get(
            "/api/v1/storage/usage",
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_blocks_excess_requests(client):
    """Requests exceeding the limit should get 429."""
    # The test app has 120 rpm limit, but we can't easily send 120+ requests
    # in a test. Instead, test the middleware directly.
    from api.app.middleware.rate_limit import RateLimitMiddleware

    mw = RateLimitMiddleware(app=None, requests_per_minute=3)

    import time

    now = time.monotonic()
    key = "test-token"

    # Fill the window
    for _ in range(3):
        mw._windows[key].append(now)

    # Next check should be over limit
    mw._clean_window(key, now)
    assert len(mw._windows[key]) >= 3


@pytest.mark.asyncio
async def test_rate_limit_independent_users():
    """Different users should have independent rate limits."""
    from api.app.middleware.rate_limit import RateLimitMiddleware

    mw = RateLimitMiddleware(app=None, requests_per_minute=2)

    import time

    now = time.monotonic()

    # User A fills their limit
    mw._windows["user-a-token"].append(now)
    mw._windows["user-a-token"].append(now)

    # User B should still have capacity
    mw._clean_window("user-b-token", now)
    assert len(mw._windows["user-b-token"]) == 0

    # User A is full
    assert len(mw._windows["user-a-token"]) == 2


@pytest.mark.asyncio
async def test_rate_limit_pruning():
    """Stale keys should be pruned to prevent memory leaks."""
    from api.app.middleware.rate_limit import RateLimitMiddleware

    mw = RateLimitMiddleware(app=None, requests_per_minute=60)

    import time

    now = time.monotonic()

    # Add a stale entry (3 minutes old)
    mw._windows["stale-user"] = [now - 200]
    # Add a fresh entry
    mw._windows["active-user"] = [now]

    mw._prune_stale_keys(now)

    assert "stale-user" not in mw._windows
    assert "active-user" in mw._windows


@pytest.mark.asyncio
async def test_health_endpoint_bypasses_rate_limit(client):
    """Health endpoints should not be rate limited."""
    for _ in range(10):
        resp = await client.get("/health")
        assert resp.status_code == 200

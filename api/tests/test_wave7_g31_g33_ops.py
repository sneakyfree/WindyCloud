"""GAP G31 + G33 — ops-polish.

G31: /health and /api/v1/status were leaking deployment metadata
(storage_provider, compute_provider, storage_healthy, compute_healthy,
version, uptime) to any internet caller. Post-fix:
  - public /health returns status + service name only
  - /health/full carries the detailed info, include_in_schema=False,
    intended for internal ALB target groups
  - /api/v1/status keeps pillar on/off booleans but drops backend names

G33: startup background tasks (retention_cleanup, billing_snapshot)
caught every exception and silently continued. That turns a credential
rotation into a weeks-long silent data-retention outage. The new
wrapper logs + captures to Sentry (if configured) + returns a bool so
the caller can metric it.
"""

from __future__ import annotations

import logging

import pytest

# ---------------------------------------------------------------------------
# G31 — /health is minimal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_public_health_returns_only_status(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"status", "service"}
    assert body["service"] == "windy-cloud"
    assert body["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_public_health_does_not_leak_provider_names(client):
    resp = await client.get("/health")
    body = resp.json()
    # These keys are now on /health/full only.
    for leaky_key in (
        "storage_provider",
        "compute_provider",
        "storage_healthy",
        "compute_healthy",
        "version",
        "uptime_seconds",
        "database",
    ):
        assert leaky_key not in body, f"/health leaked {leaky_key}: {body}"


@pytest.mark.asyncio
async def test_public_status_does_not_leak_provider_names(client):
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    # Pillars are present, but each pillar must not carry `provider`.
    for pillar in body["pillars"].values():
        assert set(pillar.keys()) == {"enabled"}, (
            f"/status pillar leaks fields: {pillar}"
        )


@pytest.mark.asyncio
async def test_health_full_exposes_detailed_info(client):
    """The internal /health/full endpoint still has the detail we used
    to return on /health — we just don't expose it publicly."""
    resp = await client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    # These are intentionally present on the internal endpoint.
    assert body["service"] == "windy-cloud"
    assert "storage_provider" in body
    assert "compute_provider" in body
    assert "uptime_seconds" in body
    assert "version" in body


# ---------------------------------------------------------------------------
# G33 — startup task failures reach Sentry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_startup_task_success_returns_true(caplog):
    from api.app.main import _run_one_startup_task

    async def ok_task(db):
        return None

    with caplog.at_level(logging.ERROR):
        ok = await _run_one_startup_task("fake_ok", ok_task)

    assert ok is True
    assert not any(
        "Startup task fake_ok failed" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_startup_task_failure_returns_false_and_logs(caplog):
    from api.app.main import _run_one_startup_task

    async def bad_task(db):
        raise RuntimeError("R2 credentials rotated, forgot to update ours")

    with caplog.at_level(logging.ERROR):
        ok = await _run_one_startup_task("fake_bad", bad_task)

    assert ok is False
    assert any(
        "Startup task fake_bad failed" in r.message for r in caplog.records
    ), "Failure must log loudly — ops needs to see it"


@pytest.mark.asyncio
async def test_startup_task_failure_captures_to_sentry(monkeypatch):
    """When sentry_sdk is available, exceptions must flow through
    capture_exception — not just log and vanish."""
    captured = []

    class _FakeSentry:
        def capture_exception(self, exc):
            captured.append(exc)

    # Inject a fake sentry_sdk into sys.modules so the conditional
    # import inside _run_one_startup_task finds it.
    import sys

    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    from api.app.main import _run_one_startup_task

    async def bad_task(db):
        raise ValueError("simulated provider error")

    ok = await _run_one_startup_task("sentry_test", bad_task)
    assert ok is False
    assert len(captured) == 1
    assert isinstance(captured[0], ValueError)


@pytest.mark.asyncio
async def test_sentry_missing_does_not_mask_the_logged_error(caplog):
    """Sentry is optional; its absence must not swallow the log."""
    import builtins

    orig_import = builtins.__import__

    def _no_sentry(name, *a, **kw):
        if name == "sentry_sdk":
            raise ImportError("sentry intentionally missing")
        return orig_import(name, *a, **kw)

    import sys

    # If sentry was injected by an earlier test, pop it so the import
    # inside _run_one_startup_task hits our stub ImportError path.
    sys.modules.pop("sentry_sdk", None)

    builtins.__import__ = _no_sentry
    try:
        from api.app.main import _run_one_startup_task

        async def bad_task(db):
            raise RuntimeError("boom")

        with caplog.at_level(logging.ERROR):
            ok = await _run_one_startup_task("no_sentry", bad_task)

        assert ok is False
        assert any("Startup task no_sentry failed" in r.message for r in caplog.records)
    finally:
        builtins.__import__ = orig_import

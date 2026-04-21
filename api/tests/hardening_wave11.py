"""Wave 11 hardening scenarios — not part of the default suite.

These are explicit adversarial probes. They live under api/tests/ so
the existing fixtures (in-memory sqlite, dependency overrides) apply,
but they're gated behind a `wave11` marker so a bare `pytest` run
doesn't touch them. Run with:

    uv run pytest -m wave11 api/tests/hardening_wave11.py -v

The hardening report (docs/HARDENING_REPORT.md) records the outcomes.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.wave11


@pytest.mark.asyncio
async def test_storage_upload_enforces_free_tier_quota(client):
    """Canonical path: /storage/upload respects UserPlan.quota_bytes."""
    from api.app.config import settings

    original_quota = settings.default_storage_quota
    original_max = settings.max_upload_size
    # Shrink both so the test is fast: quota = 4 KB, single-upload cap = 4 KB.
    settings.default_storage_quota = 4 * 1024
    settings.max_upload_size = 4 * 1024
    try:
        # First 3 KB upload — under quota, should succeed.
        r = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("a.bin", b"x" * 3072, "application/octet-stream")},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 200, r.text

        # Second 2 KB — 3 KB + 2 KB = 5 KB > 4 KB quota → 507.
        r2 = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("b.bin", b"y" * 2048, "application/octet-stream")},
            headers={"Authorization": "Bearer fake"},
        )
        assert r2.status_code == 507, r2.text
        assert "quota" in r2.json()["detail"].lower()
    finally:
        settings.default_storage_quota = original_quota
        settings.max_upload_size = original_max


@pytest.mark.asyncio
async def test_storage_upload_rejects_oversized_single_request(client):
    """MAX_UPLOAD_SIZE is the per-request ceiling; 413 fires before any
    quota math runs. This is why a 5 GB single-shot upload is
    impossible against the default config (cap is 256 MB)."""
    from api.app.config import settings

    original_max = settings.max_upload_size
    settings.max_upload_size = 1024  # 1 KB cap for speed
    try:
        r = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("big.bin", b"z" * 2048, "application/octet-stream")},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 413, r.text
    finally:
        settings.max_upload_size = original_max


@pytest.mark.asyncio
async def test_archive_upload_respects_user_plan_quota(client):
    """Wave 12 C-1 regression guard.

    Pre-Wave-12 /archive/* endpoints skipped the quota check. Wave 12
    lifts the check into `services/quota.py::check_quota` and calls
    it from both /storage/upload and the archive handler. The 507
    assertion here pins the fix so an accidental refactor that drops
    the call from one path trips immediately.
    """
    from api.app.config import settings

    original = settings.default_storage_quota
    settings.default_storage_quota = 1024  # 1 KB quota — tiny
    try:
        r = await client.post(
            "/api/v1/archive/chat",
            files={"file": ("a.bin", b"x" * 2048, "application/octet-stream")},
            data={"metadata": "{}"},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 507, (
            f"Wave 12 regression — /archive/* is not checking quota again. "
            f"Got {r.status_code}: {r.text}"
        )
    finally:
        settings.default_storage_quota = original


# NOTE — two scenarios that belong here but live elsewhere:
#   - Concurrent-upload quota-accounting race: verified on the LIVE
#     stack (10 x 256 KB via curl, DB row count + disk bytes match
#     exactly; see docs/HARDENING_REPORT.md §3.6).
#   - Passport revoke → frozen-gate → upload 403 cycle: already
#     covered by api/tests/test_wave2_frozen.py. The test fixture
#     overrides `require_not_blocked_for_write` with a passthrough,
#     so a fixture-based repro here would only test the override, not
#     the gate. Flagged as a conftest tradeoff in the report.


@pytest.mark.asyncio
async def test_passport_revoked_webhook_signature_replay(client):
    """Eternitas passport.revoked uses a signed JWT in the body; a
    bare HMAC signature + body isn't enough. This test documents the
    contract: an unsigned revocation ping is rejected 400, and a
    payload with a random token string is rejected 403 (invalid JWT
    signature)."""
    # Missing token → 400
    r = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"passport_number": "ET-WHATEVER", "reason": "test"},
    )
    assert r.status_code == 400

    # Garbage token → 403
    r = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={
            "token": "not.a.jwt",
            "passport_number": "ET-WHATEVER",
            "reason": "test",
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_identity_created_webhook_replay_rejected(client):
    """X-Pro-Timestamp older than 5 min must reject (replay guard)."""
    import hashlib
    import hmac
    import json

    from api.app.config import settings

    body = json.dumps(
        {
            "windy_identity_id": "wave11-replay-test",
            "tier": "free",
            "passport_number": None,
        }
    ).encode()
    # If identity_webhook_secret isn't configured on this fixture
    # env, the endpoint returns 503 — surface that explicitly.
    if not settings.identity_webhook_secret:
        settings.identity_webhook_secret = "wave11-identity-hmac-secret-deterministic"

    sig = hmac.new(settings.identity_webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    # Stale timestamp (1 hour ago)
    r = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Pro-Signature": sig,
            "X-Pro-Timestamp": "1000000000",  # year 2001
        },
    )
    assert r.status_code == 400
    assert "stale" in r.json()["detail"].lower()

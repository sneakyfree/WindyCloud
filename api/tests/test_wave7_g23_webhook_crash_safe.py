"""GAP G23: unhandled exceptions in webhook handlers return 200.

Eternitas retries a failing webhook 3 times then auto-deactivates the
platform (docs/webhooks.md §Delivery model). A deterministic bug in
our handler would take our subscription offline on retry #3 — a
production-outage-shaped risk for our own bugs.

The `crash_safe_webhook` decorator lets intentional HTTPExceptions
(bad signature, stale timestamp) propagate as usual but converts
unhandled Python exceptions into 200 + logged error. Sentry still
catches the stack; Eternitas keeps dispatching.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import pytest


WEBHOOK_SECRET = "g23-hmac-secret"


@pytest.fixture
def hmac_secret(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "identity_webhook_secret", WEBHOOK_SECRET)
    return WEBHOOK_SECRET


def _sig(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_intentional_http_exception_still_propagates(client, hmac_secret):
    """Bad signature is still 403 — the wrapper doesn't swallow
    HTTPException, only unknown exceptions."""
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=b'{"windy_identity_id":"g23","tier":"free"}',
        headers={"X-Windy-Signature": "deadbeef"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unhandled_exception_returns_200(monkeypatch, client, hmac_secret, caplog):
    """Simulate a deterministic bug inside the handler; response must
    be 200 with a logged error, not 500."""
    from api.app.routes import webhooks as wh_mod

    # Monkey-patch the internal allocate_plan to blow up — simulates
    # any code-side bug that reaches the handler body.
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated internal bug")

    monkeypatch.setattr(wh_mod, "allocate_plan", _boom)

    body = json.dumps({"windy_identity_id": "g23-crash", "tier": "free"}).encode()
    with caplog.at_level(logging.ERROR, logger=wh_mod.__name__):
        resp = await client.post(
            "/api/v1/webhooks/identity/created",
            content=body,
            headers={
                "X-Windy-Signature": _sig(body),
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200, (
        f"Unhandled exception must produce 200 so Eternitas doesn't "
        f"auto-deactivate us on retry #3. Got {resp.status_code}: {resp.text[:200]}"
    )
    assert resp.json()["status"] == "accepted_with_error"
    # The underlying bug must still be logged loudly.
    assert any("Unhandled exception" in r.message for r in caplog.records), (
        "The wrapper must still log the stack so the bug gets noticed"
    )


@pytest.mark.asyncio
async def test_unhandled_exception_in_trust_changed_returns_200(
    monkeypatch, client, caplog
):
    from api.app.config import settings

    monkeypatch.setattr(settings, "eternitas_webhook_secret", "trust-secret-g23")

    from api.app.routes import webhooks as wh_mod

    # Break the trust client so the invalidate call blows up.
    # (Pre-G6 invalidate is sync; G6 makes it async. Sync here matches
    # the main-branch signature this PR is built on.)
    class _BrokenClient:
        def invalidate(self, passport):
            raise RuntimeError("simulated trust-cache error")

    monkeypatch.setattr(wh_mod, "get_trust_client", lambda: _BrokenClient())

    body = json.dumps({
        "event": "trust.changed",
        "passport_number": "ET-BROKEN",
    }).encode()
    sig = "sha256=" + hmac.new(b"trust-secret-g23", body, hashlib.sha256).hexdigest()

    with caplog.at_level(logging.ERROR, logger=wh_mod.__name__):
        resp = await client.post(
            "/api/v1/webhooks/trust/changed",
            content=body,
            headers={
                "X-Eternitas-Signature": sig,
                "X-Eternitas-Event": "trust.changed",
                "X-Eternitas-Timestamp": str(int(time.time())),
                "X-Eternitas-Delivery": f"g23-{time.time_ns()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted_with_error"


@pytest.mark.asyncio
async def test_happy_path_still_returns_201(client, hmac_secret):
    """The wrapper must not change behaviour on the successful path."""
    body = json.dumps({"windy_identity_id": "g23-happy", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Windy-Signature": _sig(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "provisioned"

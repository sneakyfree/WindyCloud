"""Windy Admin telemetry emitter (ADR-WA-001) — unit tests.

Verifies the emitter is inert unless configured, builds a content-free
windy-cloud envelope, and never lets banned (content-like) metadata keys
through the emitter's own construction.
"""

import asyncio
import re

import pytest

from api.app import telemetry
from api.app.config import settings

# Same token set the ingest guard rejects (ADR-WA-001 §4).
_BANNED = re.compile(
    r"content|text|body|message|prompt|transcript|subject|html|completion|reply",
    re.IGNORECASE,
)


@pytest.mark.asyncio
async def test_emit_is_noop_when_unconfigured(monkeypatch):
    """No URL/token → no task scheduled, no raise."""
    monkeypatch.setattr(settings, "windy_admin_ingest_url", "", raising=False)
    monkeypatch.setattr(settings, "windy_admin_ingest_token", "", raising=False)
    sent: list = []
    monkeypatch.setattr(telemetry, "_send", lambda events: sent.append(events))
    telemetry.emit("storage.provisioned", actor_id="id123", metadata={"size_bytes": 5})
    await asyncio.sleep(0)
    assert sent == []


@pytest.mark.asyncio
async def test_emit_builds_content_free_windy_cloud_envelope(monkeypatch):
    monkeypatch.setattr(settings, "windy_admin_ingest_url", "https://admin.example", raising=False)
    monkeypatch.setattr(settings, "windy_admin_ingest_token", "tok", raising=False)
    captured: list = []

    async def _capture(events):
        captured.extend(events)

    monkeypatch.setattr(telemetry, "_send", _capture)
    telemetry.emit(
        "storage.provisioned",
        actor_id="ET26-TEST-0001",
        metadata={"product": "agent", "file_type": "backup", "size_bytes": 6_291_963,
                  "encrypted": True, "via": "service"},
    )
    # let the scheduled task run
    for _ in range(5):
        await asyncio.sleep(0)
        if captured:
            break
    assert len(captured) == 1
    ev = captured[0]
    assert ev["platform"] == "windy-cloud"
    assert ev["service"] == "windy-cloud-api"
    assert ev["event_type"] == "storage.provisioned"
    assert ev["actor_id"] == "ET26-TEST-0001"
    # No banned (content-like) metadata keys.
    for k in ev["metadata"]:
        assert not _BANNED.search(k), f"banned metadata key would 422: {k}"

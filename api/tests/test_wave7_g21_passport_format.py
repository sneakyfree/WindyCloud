"""GAP G21: passport format validation rejects path-traversal inputs.

The live adversarial probe in Wave 7 accepted
`passport_number = "../../internal-api/admin"` on POST /billing/allocate
and plan-allocated it anyway. In a world where Eternitas is reachable
from the pod, the trust client would have then built
`{eternitas}/api/v1/trust/../../internal-api/admin` — a path traversal
inside the Eternitas scope.

This test suite pins the format validator to the real contract shapes
and rejects everything else. The trust client is also tested for
defense-in-depth URL encoding.
"""

from __future__ import annotations

import pytest

from api.app.utils.passport import (
    is_valid_passport_number,
    validate_passport_number,
)


VALID_EXAMPLES = [
    # Seeded test fixtures (matches observed Eternitas seed script)
    "ET26-TEST-EXCP",
    "ET26-TEST-GOOD",
    "ET26-TEST-FAIR",
    "ET26-TEST-POOR",
    "ET26-TEST-REVD",
    "EH26-TEST-SEED",
    # Legacy formats from trust-api.md
    "ET26-K7BF-42MN",
    "ET-00482",
    "ET00001",
    # Operator
    "EH123456",
    "EH-ADMIN-001",
]

INVALID_EXAMPLES = [
    "",                              # empty
    None,                            # non-string guard
    "../../internal-api/admin",      # the live-probe payload
    "ET26-../../etc/passwd",         # traversal inside ET26 prefix
    "ET/with/slashes",               # slash chars
    "ET?query=param",                # query-string sneak
    "ET#fragment",                   # fragment
    "ET%2F..%2Ftest",                # pre-encoded traversal
    "ET test",                       # whitespace
    "et26-lower-case",               # lowercase rejected
    "XX-unknown-prefix",             # wrong prefix
    "ET" + "A" * 80,                 # over MAX_PASSPORT_LEN
    "AB12345",                       # bad prefix
    "ET\0null",                      # null byte
    "ET\nnewline",                   # newline
]


@pytest.mark.parametrize("v", VALID_EXAMPLES)
def test_valid_examples_accepted(v):
    assert is_valid_passport_number(v)
    assert validate_passport_number(v) == v


@pytest.mark.parametrize("v", INVALID_EXAMPLES)
def test_invalid_examples_rejected(v):
    assert not is_valid_passport_number(v or "")
    if v is not None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            validate_passport_number(v)
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# End-to-end: bad passport on /billing/allocate returns 422 (pydantic)
# or 400 (our validator), NEVER 200
# ---------------------------------------------------------------------------

TOKEN = "g21-svc-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", TOKEN)
    return TOKEN


@pytest.mark.asyncio
async def test_allocate_rejects_traversal_passport(client, service_token):
    """The exact live-probe payload from Wave 7 — must 422, not 200."""
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "g21-alloc-1",
            "tier": "free",
            "passport_number": "../../internal-api/admin",
        },
        headers={"X-Service-Token": TOKEN},
    )
    assert resp.status_code == 422, (
        f"Pre-G21 this returned 200; must now 422. Got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.asyncio
async def test_allocate_accepts_valid_passport(client, service_token):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "g21-alloc-ok",
            "tier": "free",
            "passport_number": "ET26-TEST-EXCP",
        },
        headers={"X-Service-Token": TOKEN},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_link_passport_rejects_traversal(client, service_token):
    resp = await client.post(
        "/api/v1/identity/link-passport",
        json={
            "windy_identity_id": "g21-link-1",
            "passport_number": "../evil",
        },
        headers={"X-Service-Token": TOKEN},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_by_passport_rejects_traversal(client, service_token):
    """The GET path param is not a Pydantic model; validated explicitly.

    Accepts either 400 (validator caught it) or 404 (Starlette's router
    treated the decoded slashes as path separators and didn't match the
    route at all) — both are secure outcomes. The one thing we must not
    see is the handler running and hitting the DB.
    """
    resp = await client.get(
        "/api/v1/identity/by-passport/..%2F..%2Fadmin",
        headers={"X-Service-Token": TOKEN},
    )
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_by_passport_plain_bad_format_returns_400(client, service_token):
    """A passport that makes it past the router but fails the format
    regex must 400 from our validator (not 200, not 404)."""
    resp = await client.get(
        "/api/v1/identity/by-passport/not-a-passport",
        headers={"X-Service-Token": TOKEN},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Defense in depth: trust client URL-encodes the path segment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trust_client_url_encodes_passport(monkeypatch):
    """If somehow a malformed passport reaches TrustClient (misconfig /
    internal call), the URL it builds must NOT contain raw slashes."""
    from api.app.services import trust_client as tc_mod
    from api.app.services.trust_client import TrustClient

    captured: dict = {}

    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url):
            captured["url"] = url
            from httpx import Response

            return Response(404, content=b"")

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _FakeAsyncClient)

    client = TrustClient(base_url="http://stub", use_mock=False)
    # Bypass route-level validation on purpose.
    await client.get_trust("../etc/passwd")
    assert "url" in captured
    assert "../" not in captured["url"], f"Raw traversal leaked through: {captured['url']}"
    assert "%2F" in captured["url"] or "%2E%2E" in captured["url"], (
        f"Expected the passport to be percent-encoded; got {captured['url']}"
    )

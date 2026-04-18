"""G11 coverage push — auth/* modules.

Targets the uncovered paths in:
  - auth/jwks.py (43% → higher): __init__, _get_client caching, validate_token,
    the two validator getters.
  - auth/webhook.py (43% → higher): empty-secret branch, verify_identity_webhook
    503 + 403, get_user_or_service service-token path, _raise_if_blocked
    trust branches, require_not_frozen.
  - auth/dependencies.py (47% → higher): get_current_user JWT validation paths.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# auth/jwks.py
# ---------------------------------------------------------------------------

def _es256_keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv_pem, priv.public_key()


def test_jwks_validate_token_happy(monkeypatch):
    """Stub the PyJWKClient + validate a token signed with the matching key."""
    from api.app.auth.jwks import JWKSValidator

    priv, pub = _es256_keypair()
    validator = JWKSValidator("http://stub/jwks")

    signing_stub = MagicMock()
    signing_stub.key = pub
    client_stub = MagicMock()
    client_stub.get_signing_key_from_jwt.return_value = signing_stub
    validator._jwk_client = client_stub
    validator._last_fetch = time.monotonic()

    token = pyjwt.encode(
        {"sub": "user-cov", "exp": int(time.time()) + 60},
        priv,
        algorithm="ES256",
    )
    claims = validator.validate_token(token)
    assert claims["sub"] == "user-cov"


def test_jwks_get_client_caches_within_ttl(monkeypatch):
    from api.app.auth import jwks as jwks_mod

    calls = {"n": 0}

    class _FakeJWKClient:
        def __init__(self, url, cache_keys=True, timeout=5):
            calls["n"] += 1

    monkeypatch.setattr(jwks_mod, "PyJWKClient", _FakeJWKClient)

    v = jwks_mod.JWKSValidator("http://x", cache_ttl=300)
    v._get_client()
    v._get_client()
    assert calls["n"] == 1, "Client must be cached within TTL"


def test_jwks_get_client_refreshes_past_ttl(monkeypatch):
    from api.app.auth import jwks as jwks_mod

    calls = {"n": 0}

    class _FakeJWKClient:
        def __init__(self, url, cache_keys=True, timeout=5):
            calls["n"] += 1

    monkeypatch.setattr(jwks_mod, "PyJWKClient", _FakeJWKClient)
    v = jwks_mod.JWKSValidator("http://x", cache_ttl=0)  # expires immediately
    v._get_client()
    time.sleep(0.01)
    v._get_client()
    assert calls["n"] >= 2, "Past TTL we should refresh"


def test_get_pro_and_eternitas_validators_are_singletons():
    from api.app.auth import jwks as jwks_mod

    jwks_mod._pro_validator = None
    jwks_mod._eternitas_validator = None

    p1 = jwks_mod.get_pro_validator()
    p2 = jwks_mod.get_pro_validator()
    assert p1 is p2

    e1 = jwks_mod.get_eternitas_validator()
    e2 = jwks_mod.get_eternitas_validator()
    assert e1 is e2

    assert p1 is not e1  # different endpoints, different singletons


def test_extract_identity_id_priority():
    from api.app.auth.jwks import extract_identity_id

    # windy_identity_id wins
    assert extract_identity_id({
        "windy_identity_id": "id-1",
        "passport_number": "ET-2",
        "sub": "sub-3",
    }) == "id-1"

    # passport_number next
    assert extract_identity_id({
        "passport_number": "ET-2",
        "sub": "sub-3",
    }) == "ET-2"

    # sub fallback
    assert extract_identity_id({"sub": "sub-3"}) == "sub-3"


# ---------------------------------------------------------------------------
# auth/webhook.py — verify_hmac_sha256 edge cases
# ---------------------------------------------------------------------------

def test_verify_hmac_empty_secret_returns_false():
    from api.app.auth.webhook import verify_hmac_sha256

    body = b"hello"
    good_sig = hmac.new(b"actual-secret", body, hashlib.sha256).hexdigest()
    # Empty secret → no verification possible, must return False.
    assert verify_hmac_sha256(body, good_sig, "") is False


def test_verify_hmac_empty_signature_returns_false():
    from api.app.auth.webhook import verify_hmac_sha256

    assert verify_hmac_sha256(b"body", "", "secret") is False


def test_verify_hmac_accepts_sha256_prefix():
    from api.app.auth.webhook import verify_hmac_sha256

    body = b"body"
    secret = "shh"
    hex_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_hmac_sha256(body, hex_sig, secret)
    # Eternitas sends "sha256=<hex>" — both forms must work.
    assert verify_hmac_sha256(body, f"sha256={hex_sig}", secret)
    assert not verify_hmac_sha256(body, "sha256=bad", secret)


# ---------------------------------------------------------------------------
# auth/webhook.py — verify_identity_webhook (the dep form)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_identity_webhook_503_when_secret_unset(monkeypatch):
    from api.app.auth.webhook import verify_identity_webhook
    from api.app.config import settings

    monkeypatch.setattr(settings, "identity_webhook_secret", "")

    class _Req:
        async def body(self):
            return b"{}"

    with pytest.raises(HTTPException) as exc:
        await verify_identity_webhook(_Req(), x_windy_signature="x")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_verify_identity_webhook_403_on_bad_sig(monkeypatch):
    from api.app.auth.webhook import verify_identity_webhook
    from api.app.config import settings

    monkeypatch.setattr(settings, "identity_webhook_secret", "secret-v1")

    class _Req:
        async def body(self):
            return b'{"hi":"there"}'

    with pytest.raises(HTTPException) as exc:
        await verify_identity_webhook(_Req(), x_windy_signature="deadbeef")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_identity_webhook_returns_body_on_valid_sig(monkeypatch):
    from api.app.auth.webhook import verify_identity_webhook
    from api.app.config import settings

    secret = "cov-secret"
    monkeypatch.setattr(settings, "identity_webhook_secret", secret)
    body = b'{"windy_identity_id":"cov"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    class _Req:
        async def body(self):
            return body

    result = await verify_identity_webhook(_Req(), x_windy_signature=sig)
    assert result == body


# ---------------------------------------------------------------------------
# auth/webhook.py — verify_service_token
# ---------------------------------------------------------------------------

def test_verify_service_token_rejects_missing_and_wrong(monkeypatch):
    from api.app.auth.webhook import verify_service_token
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", "the-right-token")

    with pytest.raises(HTTPException) as exc:
        verify_service_token(x_service_token="the-wrong-token")
    assert exc.value.status_code == 401

    # Empty settings.service_token means no valid token exists.
    monkeypatch.setattr(settings, "service_token", "")
    with pytest.raises(HTTPException) as exc:
        verify_service_token(x_service_token="anything")
    assert exc.value.status_code == 401


def test_verify_service_token_accepts_match(monkeypatch):
    from api.app.auth.webhook import verify_service_token
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", "t-ok")
    assert verify_service_token(x_service_token="t-ok") is True


# ---------------------------------------------------------------------------
# auth/webhook.py — _raise_if_blocked / require_not_frozen
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raise_if_blocked_passes_when_no_plan(db_session):
    """No UserPlan row → not frozen, no bridge → skip trust, no raise."""
    from api.app.auth.webhook import _raise_if_blocked

    await _raise_if_blocked(db_session, "no-plan-user")


@pytest.mark.asyncio
async def test_raise_if_blocked_403_when_plan_frozen(db_session):
    from api.app.auth.webhook import _raise_if_blocked
    from api.app.db.models import UserPlan

    db_session.add(UserPlan(
        identity_id="frozen-cov",
        plan_id="pro", tier="pro",
        quota_bytes=1024,
        frozen=True,
    ))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await _raise_if_blocked(db_session, "frozen-cov")
    assert exc.value.status_code == 403
    assert exc.value.detail == "frozen_account"


@pytest.mark.asyncio
async def test_raise_if_blocked_suspended_branch(db_session, monkeypatch):
    from api.app.auth.webhook import _raise_if_blocked
    from api.app.db.models import IdentityBridge, UserPlan
    from api.app.services.trust_client import TrustInfo

    db_session.add(UserPlan(
        identity_id="suspect", plan_id="pro", tier="pro", quota_bytes=1024,
    ))
    db_session.add(IdentityBridge(
        windy_identity_id="suspect", passport_number="ET-SUSP",
    ))
    await db_session.commit()

    suspended = TrustInfo(
        passport_number="ET-SUSP", status="suspended", tier_multiplier=1.0
    )

    class _Stub:
        async def get_trust(self, p):
            return suspended

    from api.app.services import trust_client as tc_mod
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: _Stub())

    with pytest.raises(HTTPException) as exc:
        await _raise_if_blocked(db_session, "suspect")
    assert exc.value.status_code == 403
    assert exc.value.detail == "suspended_account"


@pytest.mark.asyncio
async def test_raise_if_blocked_revoked_branch(db_session, monkeypatch):
    from api.app.auth.webhook import _raise_if_blocked
    from api.app.db.models import IdentityBridge, UserPlan
    from api.app.services.trust_client import TrustInfo

    db_session.add(UserPlan(
        identity_id="revoker", plan_id="pro", tier="pro", quota_bytes=1024,
    ))
    db_session.add(IdentityBridge(
        windy_identity_id="revoker", passport_number="ET-REV",
    ))
    await db_session.commit()

    revoked = TrustInfo(
        passport_number="ET-REV", status="revoked", tier_multiplier=0.0
    )

    class _Stub:
        async def get_trust(self, p):
            return revoked

    from api.app.services import trust_client as tc_mod
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: _Stub())

    with pytest.raises(HTTPException) as exc:
        await _raise_if_blocked(db_session, "revoker")
    assert exc.value.status_code == 403
    assert exc.value.detail == "frozen_account"


@pytest.mark.asyncio
async def test_raise_if_blocked_trust_none_passes(db_session, monkeypatch):
    """Trust lookup returns None → upstream unavailable, fail open."""
    from api.app.auth.webhook import _raise_if_blocked
    from api.app.db.models import IdentityBridge, UserPlan

    db_session.add(UserPlan(
        identity_id="opennet", plan_id="pro", tier="pro", quota_bytes=1024,
    ))
    db_session.add(IdentityBridge(
        windy_identity_id="opennet", passport_number="ET-OPEN",
    ))
    await db_session.commit()

    class _Stub:
        async def get_trust(self, p):
            return None

    from api.app.services import trust_client as tc_mod
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: _Stub())

    # Must not raise — fail-open on upstream unavailable.
    await _raise_if_blocked(db_session, "opennet")


@pytest.mark.asyncio
async def test_require_not_frozen_wraps_raise_if_blocked(db_session):
    from api.app.auth.dependencies import AuthenticatedUser
    from api.app.auth.webhook import require_not_frozen

    user = AuthenticatedUser(
        identity_id="wrap-test",
        claims={"sub": "wrap-test"},
        source="windy_pro",
    )
    # No UserPlan → no raise, returns the user unchanged.
    result = await require_not_frozen(user=user, db=db_session)
    assert result is user

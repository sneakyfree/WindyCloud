"""GAP G7: JWT validator enforces `aud` and `iss` when configured.

Default (env unset) preserves pre-Wave-7 behaviour — no aud/iss checks,
so existing deploys don't break. Prod flips the env vars on and gets
cross-product token confusion protection for free.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from api.app.auth.jwks import JWKSValidator


def _es256_keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_key = priv.public_key()
    return priv_pem, pub_key


def _mint(priv_pem: bytes, **claims) -> str:
    base = {"sub": "user-1", "exp": int(time.time()) + 300}
    base.update(claims)
    return pyjwt.encode(base, priv_pem, algorithm="ES256")


def _make_validator(pub_key, *, audience="", issuer=""):
    """Build a JWKSValidator with a stubbed signing-key lookup so we
    don't need a running JWKS server for the test."""
    v = JWKSValidator("http://stub/jwks", audience=audience, issuer=issuer)

    stub_client = MagicMock()
    signing_stub = MagicMock()
    signing_stub.key = pub_key
    stub_client.get_signing_key_from_jwt.return_value = signing_stub
    v._jwk_client = stub_client
    v._last_fetch = time.monotonic()
    return v


def test_default_behavior_no_aud_no_iss():
    """No audience/issuer configured → any token with a valid signature
    passes, matching pre-Wave-7 behaviour."""
    priv, pub = _es256_keypair()
    token = _mint(priv)  # no aud/iss
    v = _make_validator(pub)
    claims = v.validate_token(token)
    assert claims["sub"] == "user-1"


def test_audience_enforced_when_configured():
    priv, pub = _es256_keypair()
    v = _make_validator(pub, audience="windy-cloud")

    good = _mint(priv, aud="windy-cloud")
    assert v.validate_token(good)["aud"] == "windy-cloud"

    bad = _mint(priv, aud="windy-mail")
    with pytest.raises(pyjwt.InvalidAudienceError):
        v.validate_token(bad)

    missing = _mint(priv)  # no aud claim at all
    with pytest.raises(pyjwt.MissingRequiredClaimError):
        v.validate_token(missing)


def test_issuer_enforced_when_configured():
    priv, pub = _es256_keypair()
    v = _make_validator(pub, issuer="https://windyword.ai")

    good = _mint(priv, iss="https://windyword.ai")
    assert v.validate_token(good)["iss"] == "https://windyword.ai"

    bad = _mint(priv, iss="https://attacker.example")
    with pytest.raises(pyjwt.InvalidIssuerError):
        v.validate_token(bad)


def test_both_aud_and_iss_enforced_together():
    priv, pub = _es256_keypair()
    v = _make_validator(pub, audience="windy-cloud", issuer="https://windyword.ai")

    good = _mint(priv, aud="windy-cloud", iss="https://windyword.ai")
    v.validate_token(good)

    wrong_aud = _mint(priv, aud="wrong", iss="https://windyword.ai")
    with pytest.raises(pyjwt.InvalidAudienceError):
        v.validate_token(wrong_aud)

    wrong_iss = _mint(priv, aud="windy-cloud", iss="wrong")
    with pytest.raises(pyjwt.InvalidIssuerError):
        v.validate_token(wrong_iss)


def test_expired_token_still_rejected_regardless_of_aud_config():
    """The existing `exp` require remains in force."""
    priv, pub = _es256_keypair()
    v = _make_validator(pub)  # no aud/iss
    token = pyjwt.encode(
        {"sub": "u", "exp": int(time.time()) - 10},  # 10 s in the past
        priv,
        algorithm="ES256",
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        v.validate_token(token)


def test_settings_plumbing_passes_values_to_validators(monkeypatch):
    """get_pro_validator / get_eternitas_validator read settings and
    pass them through. Empty settings → no enforcement; non-empty →
    constructor receives them."""
    from api.app.config import settings
    from api.app.auth import jwks as jwks_mod

    monkeypatch.setattr(settings, "windy_cloud_expected_audience", "windy-cloud")
    monkeypatch.setattr(settings, "windy_pro_expected_issuer", "https://windyword.ai")
    monkeypatch.setattr(settings, "eternitas_expected_issuer", "https://eternitas.ai")
    jwks_mod._reset_validators_for_testing()

    pro = jwks_mod.get_pro_validator()
    assert pro._audience == "windy-cloud"
    assert pro._issuer == "https://windyword.ai"

    et = jwks_mod.get_eternitas_validator()
    assert et._audience == "windy-cloud"
    assert et._issuer == "https://eternitas.ai"

    jwks_mod._reset_validators_for_testing()

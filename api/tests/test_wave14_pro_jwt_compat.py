"""Wave 14 P0 — Pro→Cloud JWT compat bridge.

Pro's generateOAuthTokens() emits:
    { iss: 'windy-identity', userId, windyIdentityId, email, tier,
      accountId, type, scopes, products, client_id, scope }
— no `aud`, no `sub`. Pre-Wave-14 Cloud rejected this triple-over (wrong
iss, missing aud, missing sub). Wave 14 accepts it so paying users can
actually authenticate; Wave 15 will tighten back up once Pro emits the
canonical shape.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api.app.auth.jwks import JWKSValidator, _pro_issuer_set, extract_identity_id


def _rsa_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv_pem, priv.public_key()


def _mint_pro_shape(priv_pem: bytes, **overrides) -> str:
    """Mint a JWT with Pro's exact production claim set (no aud, no sub)."""
    claims = {
        "userId": "ident-123",
        "windyIdentityId": "ident-123",
        "email": "a@b.test",
        "tier": "free",
        "accountId": "ident-123",
        "type": "human",
        "scopes": ["windy_pro:*"],
        "products": ["windy_pro", "windy_cloud"],
        "iss": "windy-identity",
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, priv_pem, algorithm="RS256", headers={"kid": "k1"})


def _make_validator(pub_key, *, audience="", issuer=""):
    v = JWKSValidator("http://stub/jwks", audience=audience, issuer=issuer)
    stub_client = MagicMock()
    signing_stub = MagicMock()
    signing_stub.key = pub_key
    stub_client.get_signing_key_from_jwt.return_value = signing_stub
    v._jwk_client = stub_client
    v._last_fetch = time.monotonic()
    return v


# ---------------------------------------------------------------------------
# Validator accepts Pro's actual shape
# ---------------------------------------------------------------------------


def test_pro_shape_no_aud_no_sub_decodes_when_aud_not_configured():
    """The Wave-14 Pro validator runs with audience='' — Pro tokens pass."""
    priv, pub = _rsa_keypair()
    token = _mint_pro_shape(priv)
    v = _make_validator(pub, audience="", issuer=["windy-identity", "https://api.windyword.ai"])
    claims = v.validate_token(token)
    assert claims["iss"] == "windy-identity"
    assert "aud" not in claims
    assert "sub" not in claims


def test_pro_shape_canonical_iss_also_decodes():
    """Once Pro starts emitting the canonical iss, the same validator
    accepts it without re-config."""
    priv, pub = _rsa_keypair()
    token = _mint_pro_shape(priv, iss="https://api.windyword.ai")
    v = _make_validator(pub, audience="", issuer=["windy-identity", "https://api.windyword.ai"])
    claims = v.validate_token(token)
    assert claims["iss"] == "https://api.windyword.ai"


def test_wrong_issuer_still_rejected():
    """An attacker-minted token claiming iss='attacker' is still rejected."""
    priv, pub = _rsa_keypair()
    token = _mint_pro_shape(priv, iss="https://attacker.example")
    v = _make_validator(pub, audience="", issuer=["windy-identity", "https://api.windyword.ai"])
    with pytest.raises(pyjwt.InvalidIssuerError):
        v.validate_token(token)


def test_expired_pro_token_rejected():
    priv, pub = _rsa_keypair()
    token = _mint_pro_shape(priv, exp=int(time.time()) - 10)
    v = _make_validator(pub, audience="", issuer="windy-identity")
    with pytest.raises(pyjwt.ExpiredSignatureError):
        v.validate_token(token)


def test_sub_no_longer_required():
    """Wave 14 dropped `sub` from the require-list."""
    priv, pub = _rsa_keypair()
    token = _mint_pro_shape(priv)  # no sub
    v = _make_validator(pub, audience="", issuer="windy-identity")
    # Must not raise MissingRequiredClaimError.
    v.validate_token(token)


# ---------------------------------------------------------------------------
# extract_identity_id falls through Pro's camelCase + userId
# ---------------------------------------------------------------------------


def test_extract_prefers_snake_case_when_both_present():
    payload = {"windy_identity_id": "snake", "windyIdentityId": "camel"}
    assert extract_identity_id(payload) == "snake"


def test_extract_falls_through_to_camel_case():
    assert extract_identity_id({"windyIdentityId": "camel"}) == "camel"


def test_extract_falls_through_to_user_id_when_no_identity_claim():
    # Exact Pro shape, 2026-04-19 production.
    assert extract_identity_id({"userId": "u1", "accountId": "u1"}) == "u1"


def test_extract_falls_through_to_account_id_last():
    assert extract_identity_id({"accountId": "a1"}) == "a1"


def test_extract_raises_when_no_identity_claim_at_all():
    with pytest.raises(KeyError):
        extract_identity_id({"tier": "free", "email": "x@y"})


# ---------------------------------------------------------------------------
# _pro_issuer_set plumbing
# ---------------------------------------------------------------------------


def test_pro_issuer_set_empty_returns_transitional_only():
    assert _pro_issuer_set("") == "windy-identity"


def test_pro_issuer_set_configured_transitional_only_returns_string():
    assert _pro_issuer_set("windy-identity") == "windy-identity"


def test_pro_issuer_set_canonical_unions_with_transitional():
    assert _pro_issuer_set("https://api.windyword.ai") == [
        "windy-identity",
        "https://api.windyword.ai",
    ]


# ---------------------------------------------------------------------------
# CSV env var parsing (multi-value issuer / audience)
# ---------------------------------------------------------------------------


def test_csv_issuer_parses_to_list():
    """A CSV env value like "a,b,c" decomposes into a list so PyJWT
    matches against any. Single value stays a string."""
    v = JWKSValidator("http://stub", issuer="windy-identity,https://api.windyword.ai")
    assert v._issuer == ["windy-identity", "https://api.windyword.ai"]


def test_single_value_issuer_stays_string():
    v = JWKSValidator("http://stub", issuer="https://api.windyword.ai")
    assert v._issuer == "https://api.windyword.ai"


def test_empty_issuer_is_none():
    v = JWKSValidator("http://stub", issuer="")
    assert v._issuer is None

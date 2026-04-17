"""JWKS fetcher and JWT validator for Windy Pro / Eternitas tokens.

Wave 7 G7 — supports optional `audience` / `issuer` enforcement. When
the corresponding env settings are non-empty, PyJWT validates those
claims and rejects tokens whose `aud`/`iss` don't match. When they're
empty (default), validation falls back to the original signature-only
behaviour — no breaking change for existing deploys.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
from jwt import PyJWKClient


class JWKSValidator:
    """Fetches JWKS from a remote endpoint and validates RS256/ES256 JWTs.

    `audience` / `issuer`: when non-empty, passed to `jwt.decode` so
    PyJWT rejects tokens whose claims don't match. When empty, no
    corresponding validation runs — matches pre-Wave-7 behaviour.
    """

    def __init__(
        self,
        jwks_url: str,
        cache_ttl: int = 300,
        *,
        audience: str = "",
        issuer: str = "",
    ):
        self.jwks_url = jwks_url
        self._cache_ttl = cache_ttl
        self._audience = audience or None
        self._issuer = issuer or None
        self._jwk_client: PyJWKClient | None = None
        self._last_fetch: float = 0

    def _get_client(self) -> PyJWKClient:
        now = time.monotonic()
        if self._jwk_client is None or (now - self._last_fetch) > self._cache_ttl:
            self._jwk_client = PyJWKClient(self.jwks_url, cache_keys=True, timeout=5)
            self._last_fetch = now
        return self._jwk_client

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT and return its decoded claims.

        Raises jwt.exceptions.PyJWTError on any validation failure —
        including `InvalidAudienceError` / `InvalidIssuerError` when
        `audience` / `issuer` are configured and the token's claims
        don't match.
        """
        client = self._get_client()
        signing_key = client.get_signing_key_from_jwt(token)
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256", "ES256"],
            "options": {"require": ["exp", "sub"]},
        }
        if self._audience is not None:
            decode_kwargs["audience"] = self._audience
        if self._issuer is not None:
            decode_kwargs["issuer"] = self._issuer
        return jwt.decode(token, signing_key.key, **decode_kwargs)


# Singletons — initialized from config at import time
_pro_validator: JWKSValidator | None = None
_eternitas_validator: JWKSValidator | None = None


def get_pro_validator() -> JWKSValidator:
    global _pro_validator
    if _pro_validator is None:
        from api.app.config import settings

        _pro_validator = JWKSValidator(
            settings.windy_pro_jwks_url,
            audience=settings.windy_cloud_expected_audience,
            issuer=settings.windy_pro_expected_issuer,
        )
    return _pro_validator


def get_eternitas_validator() -> JWKSValidator:
    global _eternitas_validator
    if _eternitas_validator is None:
        from api.app.config import settings

        _eternitas_validator = JWKSValidator(
            settings.eternitas_jwks_url,
            audience=settings.windy_cloud_expected_audience,
            issuer=settings.eternitas_expected_issuer,
        )
    return _eternitas_validator


def _reset_validators_for_testing() -> None:
    """Tests that swap the underlying settings must call this to force
    singleton rebuild."""
    global _pro_validator, _eternitas_validator
    _pro_validator = None
    _eternitas_validator = None


def extract_identity_id(claims: dict[str, Any]) -> str:
    """Extract identity from JWT claims.

    Priority: windy_identity_id → passport_number (EPT) → sub (fallback).
    """
    return claims.get("windy_identity_id") or claims.get("passport_number") or claims["sub"]

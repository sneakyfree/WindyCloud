"""JWKS fetcher and JWT validator for Windy Pro / Eternitas tokens."""

from __future__ import annotations

import time
from typing import Any

import jwt
from jwt import PyJWKClient


class JWKSValidator:
    """Fetches JWKS from a remote endpoint and validates RS256/ES256 JWTs."""

    def __init__(self, jwks_url: str, cache_ttl: int = 300):
        self.jwks_url = jwks_url
        self._cache_ttl = cache_ttl
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

        Raises jwt.exceptions.PyJWTError on any validation failure.
        """
        client = self._get_client()
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={"require": ["exp", "sub"]},
        )


# Singletons — initialized from config at import time
_pro_validator: JWKSValidator | None = None
_eternitas_validator: JWKSValidator | None = None


def get_pro_validator() -> JWKSValidator:
    global _pro_validator
    if _pro_validator is None:
        from api.app.config import settings

        _pro_validator = JWKSValidator(settings.windy_pro_jwks_url)
    return _pro_validator


def get_eternitas_validator() -> JWKSValidator:
    global _eternitas_validator
    if _eternitas_validator is None:
        from api.app.config import settings

        _eternitas_validator = JWKSValidator(settings.eternitas_jwks_url)
    return _eternitas_validator


def extract_identity_id(claims: dict[str, Any]) -> str:
    """Extract windy_identity_id from JWT claims.

    Checks 'windy_identity_id', then 'sub' as fallback.
    """
    return claims.get("windy_identity_id") or claims["sub"]

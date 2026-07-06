"""JWKS fetcher and JWT validator for Windy Pro / Eternitas tokens.

Wave 7 G7 introduced optional `audience` / `issuer` enforcement so
tokens minted for another product couldn't authenticate.

Wave 14 P0 loosens that pass-through for the Pro→Cloud path because
Pro's production `generateOAuthTokens()` emits:
    { iss: 'windy-identity', userId, windyIdentityId, ... }
— no `aud`, no `sub`. Cloud's strict Wave-7 validator rejected every
real Pro login with 401, which left every authed Cloud endpoint
unreachable by paying users. Wave 14 therefore:

  - accepts the canonical form AND Pro's current form (iss via a list);
  - drops `sub` from the required-claims set (`extract_identity_id`
    falls through to `windyIdentityId`/`userId`);
  - leaves audience enforcement **disabled** by default — a Pro token
    with no `aud` claim must still decode. When Pro starts emitting
    `aud=windy-cloud`, set `WINDY_CLOUD_EXPECTED_AUDIENCE` to re-enable.

Wave 15 will tighten back up once Pro emits the canonical shape
(`iss=https://account.windyword.ai`, `aud=windy-cloud`, `sub=<identity_id>`).
See docs/WAVE14_FIX_REPORT.md §"Wave 15 handoff".
"""

from __future__ import annotations

import time
from typing import Any

import jwt
from jwt import PyJWKClient


def _normalize_claim_expectation(value: str | list[str]) -> str | list[str] | None:
    """Return None for empty, a list for CSV, or the single string.

    Accepting CSV via the env var lets a host config hold "windy-identity,
    https://account.windyword.ai" in a single line without touching pydantic-
    settings' parsing (which would otherwise need a validator).
    """
    if not value:
        return None
    if isinstance(value, str):
        if "," in value:
            parts = [s.strip() for s in value.split(",") if s.strip()]
            return parts if len(parts) > 1 else parts[0] if parts else None
        return value
    return list(value) if value else None


class JWKSValidator:
    """Fetches JWKS from a remote endpoint and validates RS256/ES256 JWTs.

    `audience` / `issuer` accept a single value OR a comma-separated list.
    When non-empty, PyJWT enforces the claim against the set; when empty,
    the claim is unchecked (matches Wave-14 compat with Pro's in-flight
    shape).
    """

    def __init__(
        self,
        jwks_url: str,
        cache_ttl: int = 300,
        *,
        audience: str | list[str] = "",
        issuer: str | list[str] = "",
    ):
        self.jwks_url = jwks_url
        self._cache_ttl = cache_ttl
        self._audience = _normalize_claim_expectation(audience)
        self._issuer = _normalize_claim_expectation(issuer)
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

        Wave 14: `sub` is NOT in the required-claims set — Pro currently
        omits it. `extract_identity_id` below handles the fall-through.
        Raises on signature / expiry / audience-mismatch / issuer-
        mismatch when those are configured.
        """
        client = self._get_client()
        signing_key = client.get_signing_key_from_jwt(token)
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256", "ES256"],
            "options": {"require": ["exp"]},
        }
        if self._audience is not None:
            decode_kwargs["audience"] = self._audience
        if self._issuer is not None:
            decode_kwargs["issuer"] = self._issuer
        return jwt.decode(token, signing_key.key, **decode_kwargs)


# Singletons — initialized from config at import time
_pro_validator: JWKSValidator | None = None
_eternitas_validator: JWKSValidator | None = None


# Wave 14: transitional issuer Pro currently emits. Always accepted in
# addition to the canonical form so Wave 14 works without a .env edit on
# the live host. Remove once Pro ships the Wave 15 canonical shape.
_PRO_TRANSITIONAL_ISSUER = "windy-identity"


def _pro_issuer_set(configured: str) -> str | list[str]:
    """Return the set of accepted `iss` values for Pro tokens.

    Always includes the Wave-14 transitional issuer `windy-identity`.
    If a host has pinned `WINDY_PRO_EXPECTED_ISSUER=https://account.windyword.ai`,
    the configured value is unioned in. Empty config → transitional only.
    """
    if not configured:
        return _PRO_TRANSITIONAL_ISSUER
    if configured == _PRO_TRANSITIONAL_ISSUER:
        return configured
    # Union — return a list so PyJWT's `issuer=` matches against any.
    return [_PRO_TRANSITIONAL_ISSUER, configured]


def get_pro_validator() -> JWKSValidator:
    global _pro_validator
    if _pro_validator is None:
        from api.app.config import settings

        # Wave 14: audience enforcement paused for Pro tokens specifically
        # — Pro's generateOAuthTokens() doesn't set `aud` yet, so passing
        # WINDY_CLOUD_EXPECTED_AUDIENCE through here would make PyJWT
        # raise MissingRequiredClaimError on every real token. The env
        # var is still honoured on the Eternitas validator and will be
        # re-enabled here in Wave 15 once Pro emits aud=windy-cloud. See
        # docs/WAVE14_FIX_REPORT.md §"Wave 15 handoff".
        _pro_validator = JWKSValidator(
            settings.windy_pro_jwks_url,
            audience="",
            issuer=_pro_issuer_set(settings.windy_pro_expected_issuer),
        )
    return _pro_validator


def get_eternitas_validator() -> JWKSValidator:
    global _eternitas_validator
    if _eternitas_validator is None:
        from api.app.config import settings

        # Audience enforcement is paused for Eternitas tokens too — for
        # the SAME reason it's paused for Pro tokens above (see
        # get_pro_validator). An Eternitas Passport Token (EPT) carries
        # NO `aud` claim by design: it's a single passport credential the
        # agent presents to EVERY platform (Mail, Chat, Cloud, Mind), so
        # it cannot be minted for one audience. Passing
        # WINDY_CLOUD_EXPECTED_AUDIENCE through here made PyJWT raise
        # MissingRequiredClaimError("aud") on every real EPT — which
        # 401'd every agent backup/restore against Cloud (surfaced
        # 2026-07-06 debugging Windy 0's failing backup: the Wave-14 fix
        # paused this for Pro but missed the symmetric EPT case). Issuer
        # enforcement stays on — that's the real identity check; audience
        # re-enables only if/when EPTs start carrying aud.
        _eternitas_validator = JWKSValidator(
            settings.eternitas_jwks_url,
            audience="",
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

    Wave 14: order widened to cover Pro's camelCase emission + the
    Node-side `userId`/`accountId` fallbacks. Pro currently sets
    `userId` and `windyIdentityId` but never `sub`; all three resolve
    to the same value, so any of them is correct.

    Priority: windy_identity_id → windyIdentityId → passport_number
    (EPT) → sub → userId → accountId.
    """
    for key in (
        "windy_identity_id",
        "windyIdentityId",
        "passport_number",
        "sub",
        "userId",
        "accountId",
    ):
        value = claims.get(key)
        if value:
            return str(value)
    raise KeyError("No identity claim found (tried windy_identity_id, sub, userId, …)")

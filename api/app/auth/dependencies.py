"""FastAPI authentication dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.app.auth.jwks import (
    extract_identity_id,
    get_eternitas_validator,
    get_pro_validator,
)

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


@dataclass
class AuthenticatedUser:
    """Resolved identity from a validated JWT."""

    identity_id: str
    claims: dict[str, Any]
    source: str  # "windy_pro" or "eternitas"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """Validate Bearer JWT against Windy Pro JWKS, falling back to Eternitas.

    Returns an AuthenticatedUser with the resolved windy_identity_id.
    """
    token = credentials.credentials
    last_error: Exception | None = None

    # Try Windy Pro first (most common)
    for source, get_validator in [
        ("windy_pro", get_pro_validator),
        ("eternitas", get_eternitas_validator),
    ]:
        try:
            validator = get_validator()
            claims = validator.validate_token(token)
            identity_id = extract_identity_id(claims)
            return AuthenticatedUser(
                identity_id=identity_id,
                claims=claims,
                source=source,
            )
        except (pyjwt.InvalidTokenError, pyjwt.PyJWKClientError, KeyError) as e:
            last_error = e
            continue
        except Exception:
            logger.exception("Unexpected error validating token via %s", source)
            last_error = None
            continue

    if last_error:
        logger.debug("All token validators failed: %s", last_error)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

"""FastAPI authentication dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.app.auth.jwks import (
    extract_identity_id,
    get_eternitas_validator,
    get_pro_validator,
)

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
        except Exception:
            continue

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

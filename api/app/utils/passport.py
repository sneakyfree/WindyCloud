"""Passport-number format validation (Wave 7 G21).

The live adversarial probe in Wave 7 accepted
`passport_number = "../../internal-api/admin"` on `POST /billing/allocate`
and got a plan allocated. In a world where Eternitas *is* reachable from
the cloud pod, the TrustClient would then build
`{eternitas}/api/v1/trust/../../internal-api/admin` — path traversal
within the Eternitas scope.

This module validates the format of an inbound passport number so those
inputs never reach the URL-construction site. Per the Eternitas Trust
API contract (`docs/trust-api.md`):

    passport may be a bot passport (`ET*` / `ET26-*` / legacy `ET-00482`)
    or an operator passport (`EH*`).

The regex below matches all three shapes in practice while rejecting
anything containing `/`, `?`, `#`, `..`, whitespace, or any other
URL-dangerous character. If Eternitas extends the format later, the
regex is the single point to bump.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, status

# Max length matches the DB column width (IdentityBridge.passport_number =
# String(64)). Anything longer is a sign of abuse.
MAX_PASSPORT_LEN = 64

# Uppercase alnum + hyphens only, starting with ET or EH. No `/`, `.`, etc.
_PASSPORT_RE = re.compile(r"^(ET|EH)[A-Z0-9]*(-[A-Z0-9]+)*$")


def is_valid_passport_number(raw: str) -> bool:
    if not raw or len(raw) > MAX_PASSPORT_LEN:
        return False
    return bool(_PASSPORT_RE.match(raw))


def validate_passport_number(raw: str, *, field: str = "passport_number") -> str:
    """Return `raw` if it matches the format; else raise 400.

    Callers should use this in the inbound surface (route handlers /
    Pydantic models) so a bad value never reaches URL construction or
    DB writes.
    """
    if not is_valid_passport_number(raw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field} format",
        )
    return raw

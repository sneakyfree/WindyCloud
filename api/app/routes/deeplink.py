"""windycloud:// deep-link resolution (Wave 8 — Grandma Ribbon).

The Electron shell (Windy Pro) registers the custom URL scheme and
forwards the target here for canonical resolution, so every caller
agrees on one allow-list and one set of web paths. Sanitising inputs at
this single choke-point keeps the Electron app from having to trust
whatever the OS dispatched.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter()


SCHEME = "windycloud"

# Allow-list: target → (web path, one-line description).
# Anything outside this dict is rejected. Adding a new target is a
# deliberate code change + test update, not a URL-string trick.
TARGETS: dict[str, dict[str, str]] = {
    "dashboard": {
        "web_path": "/",
        "description": "Open the Windy Cloud storage overview",
    },
    "backup": {
        "web_path": "/?action=start-backup",
        "description": "Trigger the first-backup flow for this account",
    },
    "usage": {
        "web_path": "/billing",
        "description": "Show quota meter and current usage",
    },
    "plan": {
        "web_path": "/billing?view=upgrade",
        "description": "Open the upgrade-plan flow",
    },
}

# Query params we're willing to forward through resolution. Anything
# else is dropped rather than passed along — prevents an attacker from
# smuggling arbitrary keys through windycloud://dashboard?redirect=evil.
_ALLOWED_PARAM_KEYS = {"source", "ref"}

# Values must be short alphanumeric-ish strings. Rejects quotes,
# control chars, angle brackets, ampersands — anything that would make
# the resulting URL interesting for XSS / open-redirect attempts.
_SAFE_PARAM_VALUE = re.compile(r"^[A-Za-z0-9_\-./]{1,64}$")


def _sanitize_params(raw: dict[str, str] | None) -> dict[str, str]:
    """Keep only allow-listed keys whose values match the safe pattern."""
    if not raw:
        return {}
    clean: dict[str, str] = {}
    for key, value in raw.items():
        if key not in _ALLOWED_PARAM_KEYS:
            continue
        if not isinstance(value, str):
            continue
        if not _SAFE_PARAM_VALUE.match(value):
            continue
        clean[key] = value
    return clean


def _resolve(target: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    if target not in TARGETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown deeplink target: {target!r}",
        )
    spec = TARGETS[target]
    clean_params = _sanitize_params(params)

    web_path = spec["web_path"]
    if clean_params:
        sep = "&" if "?" in web_path else "?"
        query = "&".join(f"{k}={v}" for k, v in sorted(clean_params.items()))
        web_path = f"{web_path}{sep}{query}"

    return {
        "target": target,
        "scheme": SCHEME,
        "web_path": web_path,
        "description": spec["description"],
        "params": clean_params,
    }


@router.get("/resolve")
async def resolve(
    target: str = Query(..., description="Deep-link target keyword"),
    source: str | None = Query(None),
    ref: str | None = Query(None),
) -> dict[str, Any]:
    """Resolve a `windycloud://<target>` URL to its canonical web path.

    Called by the Electron shell after the OS dispatches the custom
    scheme. Unknown targets → 400. Extra query params outside the
    allow-list are silently dropped.
    """
    extras: dict[str, str] = {}
    if source is not None:
        extras["source"] = source
    if ref is not None:
        extras["ref"] = ref
    return _resolve(target, extras)


@router.get("/manifest")
async def manifest() -> dict[str, Any]:
    """Static manifest of every supported deep-link target.

    The Electron shell fetches this once on startup so its handler
    registration stays aligned with what the backend actually accepts.
    """
    return {
        "scheme": SCHEME,
        "targets": [{"target": key, **spec} for key, spec in sorted(TARGETS.items())],
    }

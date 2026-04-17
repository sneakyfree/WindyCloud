"""Doc-cleanup sweep — verify README endpoint list matches the code.

If someone adds a route without updating README this test fails loudly,
so the doc never drifts silently. GAP G25.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute


REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


# Route paths that intentionally don't appear in the README listing.
# Keep this list narrow — everything here is a judgment call that
# another reviewer should be able to verify quickly.
_EXEMPT = {
    "/",                                  # Landing page (not an API surface)
    "/health",                            # Mentioned in running-locally section
    "/api/v1/status",                     # Mentioned in running-locally section
    "/health/full",                       # Internal-only (post-G31)
    "/api/v1/webhooks/identity/created",  # In the "Webhooks (inbound)" block
    "/api/v1/webhooks/passport/revoked",
    "/api/v1/webhooks/trust/changed",
    "/api/v1/identity/link-passport",     # In the "Identity bridge" block
}


def _live_paths() -> set[str]:
    from api.app.main import create_app

    app = create_app()
    return {
        r.path
        for r in app.routes
        if isinstance(r, APIRoute) and not r.include_in_schema is False
    }


def _readme_paths() -> set[str]:
    text = README.read_text()
    # Extract `/api/v1/...` patterns and /health
    paths = set(re.findall(r"(?<![`\\])(/api/v1/[A-Za-z0-9_{}/\-]+)", text))
    # Strip trailing punctuation that regex may grab.
    return {p.rstrip(").,:") for p in paths}


def test_readme_mentions_every_live_api_route():
    """Every non-exempt /api/v1 route in code must appear in README."""
    live = {p for p in _live_paths() if p.startswith("/api/v1/")}
    documented = _readme_paths()

    missing = set()
    for path in sorted(live):
        if path in _EXEMPT:
            continue
        # Readme uses `{passport}` / `{id}` / `{path}` generically. Convert
        # FastAPI's `{param}` placeholders to a lax form and compare.
        token_pattern = re.sub(r"\{[^}]+\}", "{}", path)
        token_regex = re.escape(token_pattern).replace(r"\{\}", r"\{[^/]+\}")
        if not any(re.fullmatch(token_regex, doc) for doc in documented):
            # Allow a prefix match (e.g. `/api/v1/archive/retrieve/{product}/{path}`
            # matches `/api/v1/archive/retrieve/{product}/{path}` in README even
            # if README used slightly different param names).
            prefix = path.split("{", 1)[0].rstrip("/")
            if prefix and any(d.startswith(prefix) for d in documented):
                continue
            missing.add(path)

    assert not missing, (
        "README is missing documentation for these live routes:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nUpdate README.md or add to _EXEMPT in this test with a reason."
    )

"""GAP G16: storage_router is no longer double-mounted.

Pre-G16 `main.py` did `app.include_router(storage_router, prefix="/api/v1")`
in addition to the canonical `/api/v1/storage` mount, exposing every
storage endpoint twice. That mirror was invisible in the schema but
fully live: `/api/v1/upload`, `/api/v1/files`, `/api/v1/files/{id}`,
`/api/v1/usage`, `/api/v1/export`, `/api/v1/breakdown`, `/api/v1/plans`,
`/api/v1/health`. Every gate added to the `/storage/` prefix had to be
remembered on the mirror.

Only `/api/v1/files` was actually called externally — windy-agent's
ecosystem-health probe (windy-agent/src/windyfly/commands/ecosystem.py:384).
We keep that alias as an explicit handler in `routes/agent_compat.py`
and drop the blanket re-mount.
"""

from __future__ import annotations

import pytest


def _all_api_route_paths(app):
    """Every registered API path, flattened across FastAPI versions.

    FastAPI >= 0.139 wraps `include_router` mounts in a lazy
    `_IncludedRouter` BaseRoute, so `app.routes` no longer contains one
    APIRoute per endpoint. Those wrappers expose the fully-prefixed
    effective routes via `effective_route_contexts()` — use that when
    present, fall back to plain APIRoute iteration on older versions.
    """
    from fastapi.routing import APIRoute

    paths = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            paths.append(r.path)
        elif hasattr(r, "effective_route_contexts"):
            paths.extend(ctx.path for ctx in r.effective_route_contexts())
    return paths


def _api_paths_under_v1_bare():
    """Return any /api/v1/* path that isn't inside a versioned prefix.

    Post-G16 the only survivors should be the windy-agent alias and
    the public status endpoint. Everything else means the double-mount
    came back.
    """
    from api.app.main import create_app

    app = create_app()
    known_prefixes = (
        "/api/v1/storage",
        "/api/v1/archive",
        "/api/v1/compute",
        "/api/v1/billing",
        "/api/v1/servers",
        "/api/v1/sync",
        "/api/v1/export",
        "/api/v1/analytics",
        "/api/v1/webhooks",
        "/api/v1/identity",
        "/api/v1/deeplink",
        "/api/v1/auth",  # web-portal email/password login (PR #61)
    )
    return sorted(
        path
        for path in _all_api_route_paths(app)
        if path.startswith("/api/v1/") and not any(path.startswith(p) for p in known_prefixes)
    )


def test_no_storage_router_mirror_routes():
    """Every /api/v1/... path should live under a known prefix except
    the windy-agent alias and /api/v1/status."""
    paths = _api_paths_under_v1_bare()
    assert set(paths) == {"/api/v1/files", "/api/v1/status"}, (
        f"Unexpected bare /api/v1/* routes: {paths}. "
        "If you need a new agent-compat alias, add it to routes/agent_compat.py "
        "rather than re-mounting a whole router."
    )


def test_shadow_endpoints_are_gone():
    """These were the shadow paths the double-mount exposed pre-G16.
    They must all 404 now."""
    from api.app.main import create_app

    app = create_app()
    live_paths = set(_all_api_route_paths(app))
    for gone in (
        "/api/v1/upload",
        "/api/v1/usage",
        "/api/v1/export",
        "/api/v1/breakdown",
        "/api/v1/plans",
        "/api/v1/health",
    ):
        assert gone not in live_paths, f"{gone} is still mounted — the G16 double-mount regressed."


@pytest.mark.asyncio
async def test_files_alias_still_works_for_windy_agent(client):
    """windy-agent ecosystem health calls GET /api/v1/files. The alias
    must keep behaving like GET /api/v1/storage/files."""
    canonical = await client.get(
        "/api/v1/storage/files",
        headers={"Authorization": "Bearer fake"},
    )
    alias = await client.get(
        "/api/v1/files",
        headers={"Authorization": "Bearer fake"},
    )
    assert canonical.status_code == 200
    assert alias.status_code == 200
    # Same schema keys
    assert set(canonical.json().keys()) == set(alias.json().keys())


@pytest.mark.asyncio
async def test_shadow_upload_is_404(client):
    """POST /api/v1/upload used to hit storage.upload_file via the
    mirror. It must now 404."""
    resp = await client.post(
        "/api/v1/upload",
        files={"file": ("x.txt", b"x", "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404

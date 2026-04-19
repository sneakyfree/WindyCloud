"""Wave 12 M-5 — Settings tolerates unknown keys in .env.

Pre-Wave-12 the Settings class defaulted to `extra="forbid"`, which
meant `POSTGRES_PASSWORD=...` in `.env` — read by docker-compose, not
by the app — aborted Python startup with a pydantic ValidationError
(`extra_forbidden`). Wave 11 hardening flagged this as M-5.

This test pins the fix by (a) instantiating Settings with an explicit
`.env` containing an unknown var, and (b) exercising the live
endpoint to confirm extras don't break startup paths either.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_settings_ignores_unknown_env_keys(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=docker-compose-only\nSOME_OTHER_UNKNOWN_VAR=whatever\nDEV_MODE=true\n"
    )

    # Instantiate a fresh Settings pointed at the temp env. If M-5 is
    # correct this returns a valid object; pre-Wave-12 it raised
    # pydantic_core.ValidationError on POSTGRES_PASSWORD.
    from api.app.config import Settings

    s = Settings(_env_file=str(env_file))
    # Known field honored:
    assert s.dev_mode is True
    # Extras dropped silently:
    assert not hasattr(s, "postgres_password")
    assert not hasattr(s, "some_other_unknown_var")


@pytest.mark.asyncio
async def test_health_endpoint_still_ok_with_extras_in_env(client):
    """Smoke test — the live stack still boots + answers /health even
    when the module-global settings were loaded from a `.env` with
    extras. conftest ensures DATABASE_URL is :memory: so this covers
    the full import + lifespan path.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

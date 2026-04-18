"""GAP G10: init_db must not race Alembic in production.

In dev_mode (default for local) create_all runs so SQLite starts fresh.
In prod (dev_mode=False) create_all is skipped so a pod that boots
before the Alembic migration task finishes doesn't silently create
tables at the current model schema without stamping alembic_version.

An escape hatch — WINDY_CLOUD_SCHEMA_BOOTSTRAP=1 — forces create_all
for one-shot throwaway databases.
"""

from __future__ import annotations

import logging
import os

import pytest


@pytest.mark.asyncio
async def test_init_db_creates_tables_in_dev(monkeypatch, tmp_path):
    """Dev mode: create_all runs, tables exist afterwards."""
    db_path = tmp_path / "dev.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.delenv("WINDY_CLOUD_SCHEMA_BOOTSTRAP", raising=False)

    # Re-import so the engine picks up the new DATABASE_URL
    import importlib

    from api.app import config as config_mod

    importlib.reload(config_mod)
    from api.app.db import engine as engine_mod

    importlib.reload(engine_mod)

    await engine_mod.init_db()

    async with engine_mod.engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'"
        )
        rows = result.fetchall()
    assert rows, "user_plans should exist after init_db in dev mode"


@pytest.mark.asyncio
async def test_init_db_skips_create_all_in_prod(monkeypatch, tmp_path, caplog):
    """Prod mode (dev_mode=False): create_all is a no-op."""
    db_path = tmp_path / "prod.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.delenv("WINDY_CLOUD_SCHEMA_BOOTSTRAP", raising=False)

    import importlib

    from api.app import config as config_mod

    importlib.reload(config_mod)
    from api.app.db import engine as engine_mod

    importlib.reload(engine_mod)

    with caplog.at_level(logging.INFO, logger=engine_mod.__name__):
        await engine_mod.init_db()

    async with engine_mod.engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'"
        )
        rows = result.fetchall()
    assert not rows, "user_plans must NOT be created when dev_mode=False"
    assert any("Skipping create_all" in r.message for r in caplog.records), (
        "Should log the intentional skip"
    )


@pytest.mark.asyncio
async def test_init_db_respects_bootstrap_escape_hatch(monkeypatch, tmp_path):
    """WINDY_CLOUD_SCHEMA_BOOTSTRAP=1 forces create_all even in prod."""
    db_path = tmp_path / "forced.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("WINDY_CLOUD_SCHEMA_BOOTSTRAP", "1")

    import importlib

    from api.app import config as config_mod

    importlib.reload(config_mod)
    from api.app.db import engine as engine_mod

    importlib.reload(engine_mod)

    await engine_mod.init_db()

    async with engine_mod.engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'"
        )
        rows = result.fetchall()
    assert rows, "Escape hatch must force create_all"

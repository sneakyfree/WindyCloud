"""SQLAlchemy async engine and session management."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Bootstrap the schema on startup.

    In dev (settings.dev_mode=True) this runs `Base.metadata.create_all`
    so a fresh SQLite file works out of the box. In production Alembic
    is the schema authority (see deploy/aws/CLOUD_DEPLOYMENT.md §4.3);
    running create_all there would race the migration task and create
    tables without stamping alembic_version — this function intentionally
    no-ops in that mode.

    To force create_all in a non-dev environment (e.g. a throwaway
    staging DB with no alembic history), set WINDY_CLOUD_SCHEMA_BOOTSTRAP=1.
    """
    import os

    force = os.environ.get("WINDY_CLOUD_SCHEMA_BOOTSTRAP") == "1"
    if not (settings.dev_mode or force):
        logger.info(
            "Skipping create_all on startup (dev_mode=False). "
            "Alembic owns the production schema."
        )
        return

    from api.app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields a DB session."""
    async with async_session() as session:
        yield session

"""Windy Cloud — Unified cloud platform for the Windy ecosystem.

Storage, compute, and servers. One cloud for all Windy products.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.app.__version__ import __version__
from api.app.config import settings

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

# --- Sentry ---
if settings.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            release=f"windy-cloud@{__version__}",
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("sentry-sdk not installed, skipping Sentry init")


async def _run_startup_tasks() -> None:
    """Run retention cleanup and billing snapshots on startup."""
    from api.app.db.engine import async_session
    from api.app.tasks.billing_snapshot import take_billing_snapshots
    from api.app.tasks.retention_cleanup import enforce_retention_days

    try:
        async with async_session() as db:
            await enforce_retention_days(db)
    except Exception:
        logger.exception("Retention cleanup failed on startup")

    try:
        async with async_session() as db:
            await take_billing_snapshots(db)
    except Exception:
        logger.exception("Billing snapshot failed on startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    from api.app.db.engine import init_db

    await init_db()

    # Run background tasks after DB is ready
    asyncio.create_task(_run_startup_tasks())

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Windy Cloud",
        description="Unified cloud platform — storage, compute, and servers.",
        version=__version__,
        lifespan=lifespan,
    )

    # Request logging
    from api.app.middleware.request_logging import RequestLoggingMiddleware

    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiting
    from api.app.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    from api.app.routes.analytics import router as analytics_router
    from api.app.routes.archive import router as archive_router
    from api.app.routes.billing import router as billing_router
    from api.app.routes.compute import router as compute_router
    from api.app.routes.export import router as export_router
    from api.app.routes.health import router as health_router
    from api.app.routes.identity import router as identity_router
    from api.app.routes.servers import router as servers_router
    from api.app.routes.storage import router as storage_router
    from api.app.routes.sync import router as sync_router
    from api.app.routes.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(storage_router, prefix="/api/v1/storage", tags=["storage"])
    app.include_router(archive_router, prefix="/api/v1/archive", tags=["archive"])
    app.include_router(compute_router, prefix="/api/v1/compute", tags=["compute"])
    app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(servers_router, prefix="/api/v1/servers", tags=["servers"])
    app.include_router(sync_router, prefix="/api/v1/sync", tags=["sync"])
    app.include_router(export_router, prefix="/api/v1/export", tags=["export"])
    app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])
    app.include_router(webhooks_router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(identity_router, prefix="/api/v1/identity", tags=["identity"])

    # Agent-compatible aliases — windy-agent calls /api/v1/files and /api/v1/billing/summary
    app.include_router(
        storage_router, prefix="/api/v1", tags=["agent-compat"], include_in_schema=False
    )

    # Static files (PWA manifest, landing page, service worker)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing():
        return (STATIC_DIR / "index.html").read_text()

    return app


app = create_app()

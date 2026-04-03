"""Windy Cloud — Unified cloud platform for the Windy ecosystem.

Storage, compute, and servers. One cloud for all Windy products.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    from api.app.db.engine import init_db

    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Windy Cloud",
        description="Unified cloud platform — storage, compute, and servers.",
        version="0.1.0",
        lifespan=lifespan,
    )

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
    from api.app.routes.health import router as health_router
    from api.app.routes.storage import router as storage_router
    from api.app.routes.archive import router as archive_router

    app.include_router(health_router)
    app.include_router(storage_router, prefix="/api/v1/storage", tags=["storage"])
    app.include_router(archive_router, prefix="/api/v1/archive", tags=["archive"])

    from api.app.routes.compute import router as compute_router
    from api.app.routes.billing import router as billing_router

    app.include_router(compute_router, prefix="/api/v1/compute", tags=["compute"])
    app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])

    from api.app.routes.servers import router as servers_router

    app.include_router(servers_router, prefix="/api/v1/servers", tags=["servers"])

    return app


app = create_app()

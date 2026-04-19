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


async def _run_one_startup_task(name: str, task_fn) -> bool:
    """Run a single background task with loud failure handling (Wave 7 G33).

    Pre-G33 the startup tasks caught every exception and silently
    continued — meaning a rotated R2 credential or a flaky Postgres
    cold-start would turn into a weeks-long silent retention-enforcement
    outage nobody noticed.

    Every failure now:
      - Logs at ERROR with stack ("Startup task {name} failed") so the
        pod's log stream shows it immediately.
      - Captures to Sentry (when available) so ops paging hits before
        anyone realises quotas haven't been enforced.
      - Returns False so the caller can emit a metric / flip a health
        flag.
    """
    from api.app.db.engine import async_session

    try:
        async with async_session() as db:
            await task_fn(db)
        return True
    except Exception as exc:
        logger.exception("Startup task %s failed", name)
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass
        return False


async def _run_startup_tasks() -> None:
    """Run retention cleanup, billing snapshots, and trust-cache warmup
    on startup. Each is routed through `_run_one_startup_task` (G33) so
    a flaky dependency paging Sentry instead of silently continuing.
    """
    from api.app.tasks.billing_snapshot import take_billing_snapshots
    from api.app.tasks.retention_cleanup import enforce_retention_days
    from api.app.tasks.trust_warmup import warmup_trust_cache

    await _run_one_startup_task("retention_cleanup", enforce_retention_days)
    await _run_one_startup_task("billing_snapshot", take_billing_snapshots)
    # G22: warm the trust cache for known passports so the first post-
    # deploy request per-passport doesn't have to do a synchronous
    # Eternitas round-trip.
    await _run_one_startup_task("trust_warmup", warmup_trust_cache)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # G4: fail fast on partial R2 config so we don't silently try to
    # write to a nonexistent bucket on the first upload.
    reason = settings.r2_misconfiguration_reason
    if reason:
        raise RuntimeError(reason)

    from api.app.db.engine import init_db

    await init_db()

    # Run background tasks after DB is ready
    asyncio.create_task(_run_startup_tasks())

    yield


def create_app() -> FastAPI:
    # Hide interactive docs + OpenAPI schema in production so the full API
    # surface (including service-token + webhook endpoints) isn't public.
    # Dev mode keeps them on for local exploration.
    if settings.dev_mode:
        openapi_kwargs: dict[str, str | None] = {}
    else:
        openapi_kwargs = {"openapi_url": None, "docs_url": None, "redoc_url": None}

    app = FastAPI(
        title="Windy Cloud",
        description="Unified cloud platform — storage, compute, and servers.",
        version=__version__,
        lifespan=lifespan,
        **openapi_kwargs,
    )

    # Request logging
    from api.app.middleware.request_logging import RequestLoggingMiddleware

    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiting
    from api.app.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

    # GAP G24: tighten CORS. `allow_origins=[...]` with `allow_credentials=True`
    # and wildcard methods/headers is a "any origin we reflect can send
    # credentials" policy — CSRF-with-credentials hazard. Pin to the
    # specific methods / headers the dashboard + SDKs actually use.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Service-Token",
            "X-Windy-Signature",
            "X-Eternitas-Signature",
            "X-Eternitas-Event",
            "X-Eternitas-Timestamp",
            "X-Eternitas-Delivery",
        ],
        expose_headers=[
            "X-Storage-Warning",
        ],
        max_age=600,
    )

    # Routers
    from api.app.routes.agent_compat import router as agent_compat_router
    from api.app.routes.analytics import router as analytics_router
    from api.app.routes.archive import router as archive_router
    from api.app.routes.billing import router as billing_router
    from api.app.routes.compute import router as compute_router
    from api.app.routes.deeplink import router as deeplink_router
    from api.app.routes.export import router as export_router
    from api.app.routes.health import router as health_router
    from api.app.routes.identity import router as identity_router
    from api.app.routes.servers import router as servers_router
    from api.app.routes.storage import router as storage_router
    from api.app.routes.stripe_webhook import router as stripe_webhook_router
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
    app.include_router(stripe_webhook_router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(identity_router, prefix="/api/v1/identity", tags=["identity"])
    app.include_router(deeplink_router, prefix="/api/v1/deeplink", tags=["deeplink"])

    # Agent-compat: the ONE endpoint windy-agent calls outside the
    # /storage/ prefix. Pre-G16 we double-mounted the whole storage
    # router here, shadow-exposing /upload, /usage, /export, /breakdown,
    # /plans, /health — none of which agents called but all of which
    # had to be remembered when adding gates. See routes/agent_compat.py.
    app.include_router(agent_compat_router, prefix="/api/v1", include_in_schema=False)

    # Static files (PWA manifest, landing page, service worker)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing():
        return (STATIC_DIR / "index.html").read_text()

    return app


app = create_app()

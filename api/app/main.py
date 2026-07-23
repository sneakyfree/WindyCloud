"""Windy Cloud — Unified cloud platform for the Windy ecosystem.

Storage, compute, and servers. One cloud for all Windy products.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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

    # Security headers (Wave 14 P1). Added after RequestLogging + RateLimit
    # so the log / rate-limit middleware runs before the response headers
    # are decorated, but before CORS so the security headers survive a
    # preflight rewrite. Starlette applies middleware bottom-up during
    # dispatch, so the order here means request hits SecurityHeaders last
    # on the way in / first on the way out — i.e. it gets to stamp every
    # response the app produces.
    from api.app.middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

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
    from api.app.routes.auth import router as auth_router
    from api.app.routes.billing import router as billing_router
    from api.app.routes.compute import router as compute_router
    from api.app.routes.deeplink import router as deeplink_router
    from api.app.routes.eternitas_dispatcher import router as eternitas_dispatcher_router
    from api.app.routes.export import router as export_router
    from api.app.routes.health import router as health_router
    from api.app.routes.identity import router as identity_router
    from api.app.routes.servers import router as servers_router
    from api.app.routes.storage import router as storage_router
    from api.app.routes.stripe_webhook import router as stripe_webhook_router
    from api.app.routes.sync import router as sync_router
    from api.app.routes.version import router as version_router
    from api.app.routes.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
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

    # Wave 14 P0: Eternitas's fanout posts every event type to a single
    # per-subscriber URL (registered in Eternitas as
    # `https://cloud.windycloud.com/webhooks/eternitas`). This dispatcher
    # reads X-Eternitas-Event and re-dispatches to the canonical per-
    # event handlers above. No prefix — the path is literal.
    app.include_router(eternitas_dispatcher_router, include_in_schema=False)

    # Static files (PWA manifest, service worker)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Serve the built React dashboard (Login / Files / Compute / Servers /
    # Billing / Settings) from the API process so cloud.windycloud.com is an
    # actual web app instead of a JSON host with a dead splash. Previously the
    # portal was never deployed and every dashboard route 404'd (SOTU-2). The
    # SPA owns "/" (its router redirects an anonymous visitor to /login), so it
    # replaces the old static marketing splash whose only CTA (/docs) 404'd in
    # prod — cloud.windycloud.com is the app host; marketing lives on the apex.
    spa_mounted = _mount_spa(app)

    if not spa_mounted:
        # API-only checkout / CI (no built dashboard): keep the minimal landing
        # so "/" still answers with an HTML page + security headers.
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def landing():
            return (STATIC_DIR / "index.html").read_text()

    return app


# Top-level path segments that must stay real API/infra surface — the SPA
# fallback must never serve index.html for these (an /api/... 404 has to remain
# a JSON 404, not a 200 HTML shell that breaks probing clients).
_RESERVED_PREFIXES = (
    "api",
    "health",
    "version",
    "docs",
    "redoc",
    "openapi.json",
    "static",
    "webhooks",
)


def _mount_spa(app: FastAPI) -> bool:
    """Serve the Vite dashboard via a 404 fallback (yields to every real route).

    Returns True when the dashboard was mounted, False when its build output is
    absent (so the caller can fall back to the minimal landing).
    """
    dist = Path(settings.web_dist_dir).resolve()
    index = dist / "index.html"
    if not index.is_file():
        logger.info("SPA disabled — %s has no index.html", dist)
        return False

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="spa-assets")

    async def _spa_or_404(request: Request, exc: StarletteHTTPException):
        full_path = request.url.path.lstrip("/")
        head = full_path.split("/", 1)[0]
        if (
            exc.status_code == 404
            and request.method in ("GET", "HEAD")
            and head not in _RESERVED_PREFIXES
        ):
            if full_path:
                candidate = (dist / full_path).resolve()
                if candidate.is_file() and candidate.is_relative_to(dist):
                    return FileResponse(candidate)
            # Client-side route (/login, /files, …) or root: hand over the shell.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return await http_exception_handler(request, exc)

    app.add_exception_handler(StarletteHTTPException, _spa_or_404)
    return True


app = create_app()

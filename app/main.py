"""
Application factory.

Create the FastAPI app via create_application().
The module-level ``app`` binding is the ASGI entry point used by uvicorn.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.core import all_models  # noqa: F401 — register all ORM models at import time
from app.core.events import lifespan
from app.core.exception_handlers import register_exception_handlers
from app.core.middleware.logging import LoggingMiddleware
from app.core.middleware.request_id import RequestIDMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.core.middleware.tenant_context import TenantContextMiddleware
from app.core.middleware.ip_block import IPBlockMiddleware
from app.core.middleware.metrics import PrometheusMiddleware


def create_application() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        debug=settings.DEBUG,
    )

    # ── Middleware ─────────────────────────────────────────────────────────
    # Registered in reverse order: last-added = first-executed at request time.
    # Execution order (outermost→innermost):
    #   SecurityHeaders → GZip → CORS → RequestID → IPBlock → Logging
    #   → TenantContext → Prometheus → route handler
    application.add_middleware(PrometheusMiddleware)
    application.add_middleware(TenantContextMiddleware)
    application.add_middleware(LoggingMiddleware)
    application.add_middleware(IPBlockMiddleware)
    application.add_middleware(RequestIDMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # GZip compresses responses larger than 1 KB — saves bandwidth without
    # any application-level work.
    application.add_middleware(GZipMiddleware, minimum_size=1024)
    # SecurityHeaders is outermost: every response — including error payloads
    # and redirects — gets the hardening headers.
    application.add_middleware(
        SecurityHeadersMiddleware,
        is_production=settings.is_production,
    )

    # ── Routers ────────────────────────────────────────────────────────────
    _register_routers(application)

    # ── Exception handlers ─────────────────────────────────────────────────
    register_exception_handlers(application)

    return application


def _register_routers(app: FastAPI) -> None:
    """Import and mount all module routers."""
    from fastapi import APIRouter
    from datetime import datetime, UTC

    # ── Health check ───────────────────────────────────────────────────────
    health_router = APIRouter()

    @health_router.get("/health", tags=["System"])
    async def health() -> dict:
        return {
            "status": "ok",
            "version": get_settings().APP_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    app.include_router(health_router)

    # ── Module routers (uncomment as each module is implemented) ───────────
    from app.modules.auth.router import router as auth_router
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])

    from app.modules.tenancy.router import router as tenancy_router
    app.include_router(tenancy_router, prefix="/api/v1", tags=["Tenancy"])

    from app.modules.billing.router import router as billing_router
    app.include_router(billing_router, prefix="/api/v1/billing", tags=["Billing"])

    from app.modules.rbac.router import router as rbac_router
    app.include_router(rbac_router, prefix="/api/v1/rbac", tags=["RBAC"])

    from app.modules.features.router import router as features_router
    app.include_router(features_router, prefix="/api/v1", tags=["Features"])

    from app.modules.audit.router import router as audit_router
    app.include_router(audit_router, prefix="/api/v1", tags=["Audit"])

    from app.modules.security.router import router as security_router
    app.include_router(security_router, prefix="/api/v1", tags=["Security"])

    # from app.modules.notifications.router import router as notifications_router
    # app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["Notifications"])

    from app.modules.notifications.router import router as notifications_router
    app.include_router(notifications_router, prefix="/api/v1", tags=["Notifications"])

    # from app.modules.files.router import router as files_router
    # app.include_router(files_router, prefix="/api/v1/files", tags=["Files"])
    from app.modules.files.router import router as files_router
    app.include_router(files_router, prefix="/api/v1/files", tags=["Files"])

    from app.modules.api_management.router import router as api_mgmt_router
    app.include_router(api_mgmt_router, prefix="/api/v1", tags=["API Management"])

    from app.modules.system.router import router as system_router
    app.include_router(system_router, prefix="/api/v1", tags=["System"])

    from app.modules.agents.router import router as agents_router
    app.include_router(agents_router, prefix="/api/v1", tags=["Agents"])

    from app.modules.dashboard.router import router as dashboard_router
    app.include_router(dashboard_router, prefix="/api/v1", tags=["Dashboard"])


app = create_application()

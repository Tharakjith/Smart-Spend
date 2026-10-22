import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import install_error_handlers

settings = get_settings()
logging.basicConfig(level=settings.log_level)


def create_app() -> FastAPI:
    app = FastAPI(
        title="SmartSpend API",
        version="1.0.0",
        description="Expense management with explainable bill/payment reconciliation. All money values are decimal strings.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Household-ID", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith(settings.api_prefix):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    from app.modules.analytics.router import router as analytics
    from app.modules.auth.router import router as auth
    from app.modules.catalog.router import router as catalog
    from app.modules.households.router import router as households
    from app.modules.ledger.router import router as ledger
    from app.modules.reconciliation.router import router as reconciliation

    for r in (auth, households, catalog, ledger, reconciliation, analytics):
        app.include_router(r, prefix=settings.api_prefix)

    try:  # later-phase modules register themselves when present
        from app.modules import extra_routers

        for r in extra_routers.ROUTERS:
            app.include_router(r, prefix=settings.api_prefix)
    except ImportError as exc:  # pragma: no cover
        if "extra_routers" not in str(exc):
            raise

    @app.get("/api/health", tags=["health"])
    def health():
        from sqlalchemy import text

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            db.execute(text("select 1"))
        return {"status": "ok"}

    return app


app = create_app()

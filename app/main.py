from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.routes import chats, collector, graph, media, messages, profiles, stats
from app.core.config import settings
from app.database.migration_check import require_current_database_revision
from app.database.session import close_database, engine
from app.core.logging import configure_logging
from app.web.routes import router as web_router
from app.web.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings)
    logger.info("Starting API application")
    try:
        await require_current_database_revision(engine)
        logger.info("PostgreSQL schema matches the Alembic head")
    except Exception:
        logger.exception("Database startup validation failed")
        await close_database()
        raise
    yield
    await close_database()
    logger.info("API application stopped")


app = FastAPI(title="SaparGuard Telegram Collector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(web_router)
app.include_router(chats.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(profiles.vehicles_router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(collector.router, prefix="/api")
app.include_router(graph.router, prefix="/api")


@app.middleware("http")
async def add_web_security_headers(request: Request, call_next):
    """Apply strict headers only to server-rendered UI, preserving Swagger compatibility."""
    request.state.locale = request.cookies.get("saparguard_locale", DEFAULT_LOCALE)
    if request.state.locale not in SUPPORTED_LOCALES:
        request.state.locale = DEFAULT_LOCALE
    response = await call_next(request)
    excluded_paths = ("/api", "/docs", "/redoc", "/openapi.json", "/static", "/health")
    if request.url.path.startswith(excluded_paths):
        return response
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self'; object-src 'none'; script-src 'self'; style-src 'self'"
    )
    return response


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import chats, collector, graph, media, messages, profiles, stats
from app.auth.google import initialize_google_provider
from app.auth.service import (
    AuthenticationError,
    bootstrap_default_admin,
    decode_access_token,
    get_active_user_by_id,
    require_jwt_configuration,
)
from app.core.config import settings
from app.database.migration_check import require_current_database_revision
from app.database.models import UserRole
from app.database.session import SessionFactory, close_database, engine
from app.core.logging import configure_logging
from app.web.routes import router as web_router
from app.web.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings)
    logger.info("Starting API application")
    try:
        require_jwt_configuration()
        await require_current_database_revision(engine)
        async with SessionFactory() as session:
            async with session.begin():
                await bootstrap_default_admin(session)
        initialize_google_provider()
        logger.info("PostgreSQL schema matches the Alembic head")
    except Exception:
        logger.exception("Database startup validation failed")
        await close_database()
        raise
    yield
    await close_database()
    logger.info("API application stopped")


app = FastAPI(title="SaparGuard Telegram Collector", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret or "saparguard-invalid-auth-configuration",
    https_only=settings.jwt_cookie_secure,
    same_site="lax",
)
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
    path = request.url.path
    public_paths = {
        "/health",
        "/auth/login",
        "/auth/register",
        "/auth/google",
        "/auth/google/callback",
        "/ui/actions/locale",
    }
    if path.startswith("/static") or path in public_paths:
        response = await call_next(request)
        return _apply_web_security_headers(request, response)

    invalid_cookie = False
    token = request.cookies.get(settings.jwt_cookie_name)
    if token:
        try:
            user_id = decode_access_token(token)
            async with SessionFactory() as session:
                request.state.user = await get_active_user_by_id(session, user_id)
            if request.state.user is None:
                invalid_cookie = True
        except AuthenticationError:
            invalid_cookie = True

    user = getattr(request.state, "user", None)
    if user is None:
        response = _access_denied_response(request, 401, "Требуется вход в систему.")
        if invalid_cookie:
            response.delete_cookie(settings.jwt_cookie_name, path="/")
        return _apply_web_security_headers(request, response)

    if user.role == UserRole.CITIZEN.value and not (
        path.startswith("/complaints")
        or path.startswith("/account")
        or path == "/auth/me"
        or path == "/auth/account"
        or path == "/auth/logout"
        or path == "/ui/actions/locale"
    ):
        return _apply_web_security_headers(
            request,
            _access_denied_response(request, 403, "Этот раздел доступен только сотрудникам."),
        )
    if user.role == UserRole.WORKER.value and path.startswith("/admin"):
        return _apply_web_security_headers(
            request,
            _access_denied_response(request, 403, "У вас нет доступа к управлению пользователями."),
        )
    response = await call_next(request)
    return _apply_web_security_headers(request, response)


def _is_api_request(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api") or "application/json" in accept


def _access_denied_response(request: Request, status_code: int, message: str):
    if _is_api_request(request):
        return JSONResponse({"detail": message}, status_code=status_code)
    if status_code == 401:
        return RedirectResponse("/auth/login", status_code=303)
    from app.web.templating import templates

    user = getattr(request.state, "user", None)
    return templates.TemplateResponse(
        request,
        "pages/error.html",
        {
            "title": "Доступ запрещён",
            "message": message,
            "user": user,
            "home_url": "/complaints" if user and user.role == UserRole.CITIZEN.value else "/",
        },
        status_code=status_code,
    )


def _apply_web_security_headers(request: Request, response):
    excluded_paths = ("/api", "/docs", "/redoc", "/openapi.json", "/static", "/health")
    if request.url.path.startswith(excluded_paths):
        return response
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self'; object-src 'none'; "
        "script-src 'self' https://accounts.google.com; style-src 'self'; "
        "frame-src https://accounts.google.com; connect-src 'self' https://accounts.google.com"
    )
    return response


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

"""Public local authentication and optional Google OIDC endpoints."""

from __future__ import annotations

from urllib.parse import urlencode

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import google_auth_available, google_client
from app.auth.service import (
    AuthenticationError,
    authenticate_local_user,
    create_access_token,
    link_google_account,
    register_local_user,
)
from app.core.config import settings
from app.database.models import AppUser, UserRole
from app.database.session import get_session
from app.web.templating import templates

router = APIRouter(prefix="/auth")


def _redirect(path: str, **values: str) -> RedirectResponse:
    query = urlencode({key: value for key, value in values.items() if value})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


def _signed_in_response(user: AppUser) -> RedirectResponse:
    destination = "/complaints" if user.role == UserRole.CITIZEN.value else "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        settings.jwt_cookie_name,
        create_access_token(user),
        httponly=True,
        secure=settings.jwt_cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None, registered: bool = False) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/login.html",
        {
            "error": error,
            "registered": registered,
            "google_available": google_auth_available(),
        },
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    async with session.begin():
        user = await authenticate_local_user(session, email=email, password=password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "pages/login.html",
            {
                "error": "Неверный email, пароль или доступ заблокирован.",
                "registered": False,
                "google_available": google_auth_available(),
            },
            status_code=401,
        )
    return _signed_in_response(user)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "pages/register.html", {"error": error})


@router.post("/register", response_class=HTMLResponse, response_model=None)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    if password != password_confirmation:
        return templates.TemplateResponse(
            request,
            "pages/register.html",
            {"error": "Пароли не совпадают."},
            status_code=422,
        )
    try:
        async with session.begin():
            await register_local_user(session, email=email, password=password)
    except AuthenticationError as error:
        return templates.TemplateResponse(
            request, "pages/register.html", {"error": str(error)}, status_code=422
        )
    return _redirect("/auth/login", registered="1")


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(settings.jwt_cookie_name, path="/")
    return response


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    user = request.state.user
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "registration_source": user.registration_source,
    }


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "pages/account.html", {"user": request.state.user})


@router.get("/google")
async def google_login(request: Request) -> RedirectResponse:
    client = google_client()
    if client is None:
        return _redirect("/auth/login", error="Google-аутентификация сейчас недоступна.")
    return await client.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback")
async def google_callback(
    request: Request, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    client = google_client()
    if client is None:
        return _redirect("/auth/login", error="Google-аутентификация сейчас недоступна.")
    try:
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not isinstance(userinfo, dict):
            return _redirect("/auth/login", error="Google не вернул данные профиля.")
        subject = userinfo.get("sub")
        email = userinfo.get("email")
        if not isinstance(subject, str) or not isinstance(email, str):
            return _redirect("/auth/login", error="Google не вернул обязательные данные профиля.")
        async with session.begin():
            user = await link_google_account(
                session,
                google_account_id=subject,
                email=email,
                email_verified=userinfo.get("email_verified") is True,
            )
    except (OAuthError, AuthenticationError):
        return _redirect("/auth/login", error="Не удалось завершить вход через Google.")
    return _signed_in_response(user)

"""Administrator-only account management with soft-delete safeguards."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.service import (
    AuthenticationError,
    hash_password,
    normalize_and_validate_email,
    validate_password,
)
from app.core.config import settings
from app.database.models import AppUser, Complaint, UserRole
from app.database.session import get_session
from app.web.templating import templates

router = APIRouter(prefix="/admin/users")
PAGE_SIZE = 25


def _roles() -> tuple[str, ...]:
    return tuple(role.value for role in UserRole)


def _normalized_display_email(email: str) -> tuple[str, str]:
    return normalize_and_validate_email(email)


def _form_values(
    *, email: str, role: str, is_active: bool, remove_local_login: bool = False
) -> dict[str, object]:
    return {
        "email": email,
        "role": role,
        "is_active": is_active,
        "remove_local_login": remove_local_login,
    }


async def _is_last_active_admin(session: AsyncSession, user: AppUser) -> bool:
    if user.role != UserRole.ADMIN.value or not user.is_active or user.deleted_at is not None:
        return False
    count = await session.scalar(
        select(func.count(AppUser.id)).where(
            AppUser.role == UserRole.ADMIN.value,
            AppUser.is_active.is_(True),
            AppUser.deleted_at.is_(None),
        )
    )
    return count == 1


def _requires_self_confirmation(
    current_admin: AppUser, target: AppUser, *, role: str, is_active: bool
) -> bool:
    return current_admin.id == target.id and (role != UserRole.ADMIN.value or not is_active)


@router.get("", response_class=HTMLResponse)
async def users_list(
    request: Request,
    email: str | None = None,
    role: str | None = None,
    state: str | None = None,
    page: int = 1,
    _: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    statement = select(AppUser)
    if email:
        statement = statement.where(AppUser.normalized_email.ilike(f"%{email.strip()}%"))
    if role in _roles():
        statement = statement.where(AppUser.role == role)
    if state == "active":
        statement = statement.where(AppUser.is_active.is_(True), AppUser.deleted_at.is_(None))
    elif state == "blocked":
        statement = statement.where(AppUser.is_active.is_(False), AppUser.deleted_at.is_(None))
    elif state == "deleted":
        statement = statement.where(AppUser.deleted_at.is_not(None))
    else:
        statement = statement.where(AppUser.deleted_at.is_(None))
    page = max(page, 1)
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    users = list(
        (
            await session.scalars(
                statement.order_by(AppUser.created_at.desc(), AppUser.id.desc())
                .offset((page - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE)
            )
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "pages/admin_users.html",
        {
            "users": users,
            "roles": _roles(),
            "filters": {
                "email": email or "",
                "role": role or "",
                "state": state or "",
                "page": page,
            },
            "pagination": {"page": page, "has_more": page * PAGE_SIZE < total, "total": total},
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def user_create_page(request: Request, _: AppUser = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request, "pages/admin_user_form.html", {"roles": _roles()})


@router.post("/new", response_class=HTMLResponse, response_model=None)
async def user_create(
    request: Request,
    email: str = Form(default=""),
    password: str = Form(...),
    role: str = Form(UserRole.CITIZEN.value),
    is_active: bool = Form(False),
    _: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    if role not in _roles():
        raise HTTPException(status_code=422, detail="Некорректная роль.")
    try:
        display_email, normalized_email = _normalized_display_email(email)
        validate_password(password)
        now = datetime.now(timezone.utc)
        async with session.begin():
            existing = await session.scalar(
                select(AppUser).where(AppUser.normalized_email == normalized_email)
            )
            if existing is not None:
                raise AuthenticationError("Пользователь с таким email уже существует.")
            user = AppUser(
                email=display_email,
                normalized_email=normalized_email,
                password_hash=hash_password(password),
                role=role,
                is_active=is_active,
                registration_source="local",
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            await session.flush()
    except AuthenticationError as error:
        return templates.TemplateResponse(
            request,
            "pages/admin_user_form.html",
            {
                "roles": _roles(),
                "error": str(error),
                "form": _form_values(email=email, role=role, is_active=is_active),
            },
            status_code=422,
        )
    except IntegrityError:
        return templates.TemplateResponse(
            request,
            "pages/admin_user_form.html",
            {
                "roles": _roles(),
                "error": "Пользователь с таким email уже существует.",
                "form": _form_values(email=email, role=role, is_active=is_active),
            },
            status_code=422,
        )
    return RedirectResponse(f"/admin/users/{user.id}", status_code=303)


@router.get("/{user_id}", response_class=HTMLResponse)
async def user_detail(
    user_id: int,
    request: Request,
    _: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    complaint_count = (
        await session.scalar(select(func.count(Complaint.id)).where(Complaint.author_id == user.id))
        or 0
    )
    return templates.TemplateResponse(
        request,
        "pages/admin_user_detail.html",
        {"managed_user": user, "roles": _roles(), "complaint_count": complaint_count},
    )


@router.post("/{user_id}", response_model=None)
async def user_update(
    user_id: int,
    request: Request,
    email: str = Form(default=""),
    role: str = Form(...),
    is_active: bool = Form(False),
    password: str | None = Form(default=None),
    remove_local_login: bool = Form(False),
    confirm_self_lockout: bool = Form(False),
    current_admin: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    if role not in _roles():
        raise HTTPException(status_code=422, detail="Некорректная роль.")
    try:
        display_email, normalized_email = _normalized_display_email(email)
        async with session.begin():
            user = await session.get(AppUser, user_id)
            if user is None or user.deleted_at is not None:
                raise HTTPException(status_code=404, detail="User not found")
            existing = await session.scalar(
                select(AppUser).where(
                    AppUser.normalized_email == normalized_email, AppUser.id != user.id
                )
            )
            if existing is not None:
                raise AuthenticationError("Пользователь с таким email уже существует.")
            changes_active_admin = (
                user.role == UserRole.ADMIN.value
                and user.is_active
                and (role != UserRole.ADMIN.value or not is_active)
            )
            if changes_active_admin and await _is_last_active_admin(session, user):
                raise HTTPException(
                    status_code=409, detail="Нельзя изменить последнего активного администратора."
                )
            if (
                _requires_self_confirmation(current_admin, user, role=role, is_active=is_active)
                and not confirm_self_lockout
            ):
                raise HTTPException(
                    status_code=409, detail="Подтвердите изменение собственного доступа."
                )
            if remove_local_login and user.google_account_id is None:
                raise HTTPException(
                    status_code=422, detail="Нельзя удалить единственный способ входа."
                )
            if password:
                validate_password(password)
                user.password_hash = hash_password(password)
            elif remove_local_login:
                user.password_hash = None
            user.email = display_email
            user.normalized_email = normalized_email
            user.role = role
            user.is_active = is_active
            user.updated_at = datetime.now(timezone.utc)
    except AuthenticationError as error:
        user = await session.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        complaint_count = (
            await session.scalar(
                select(func.count(Complaint.id)).where(Complaint.author_id == user.id)
            )
            or 0
        )
        return templates.TemplateResponse(
            request,
            "pages/admin_user_detail.html",
            {
                "managed_user": user,
                "roles": _roles(),
                "complaint_count": complaint_count,
                "error": str(error),
                "form": _form_values(
                    email=email,
                    role=role,
                    is_active=is_active,
                    remove_local_login=remove_local_login,
                ),
            },
            status_code=422,
        )
    except IntegrityError:
        await session.rollback()
        user = await session.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        complaint_count = (
            await session.scalar(
                select(func.count(Complaint.id)).where(Complaint.author_id == user.id)
            )
            or 0
        )
        return templates.TemplateResponse(
            request,
            "pages/admin_user_detail.html",
            {
                "managed_user": user,
                "roles": _roles(),
                "complaint_count": complaint_count,
                "error": "Пользователь с таким email уже существует.",
                "form": _form_values(
                    email=email,
                    role=role,
                    is_active=is_active,
                    remove_local_login=remove_local_login,
                ),
            },
            status_code=422,
        )
    response = RedirectResponse(f"/admin/users/{user_id}", status_code=303)
    if current_admin.id == user_id and not is_active:
        response.delete_cookie(settings.jwt_cookie_name, path="/")
    return response


@router.post("/{user_id}/delete")
async def user_delete(
    user_id: int,
    confirm_self_lockout: bool = Form(False),
    current_admin: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    async with session.begin():
        user = await session.get(AppUser, user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status_code=404, detail="User not found")
        if await _is_last_active_admin(session, user):
            raise HTTPException(
                status_code=409, detail="Нельзя удалить последнего активного администратора."
            )
        if current_admin.id == user.id and not confirm_self_lockout:
            raise HTTPException(
                status_code=409, detail="Подтвердите удаление собственной учётной записи."
            )
        user.is_active = False
        user.deleted_at = datetime.now(timezone.utc)
        user.updated_at = user.deleted_at
    response = RedirectResponse("/admin/users", status_code=303)
    if current_admin.id == user_id:
        response.delete_cookie(settings.jwt_cookie_name, path="/")
    return response


@router.post("/{user_id}/restore")
async def user_restore(
    user_id: int,
    _: AppUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    async with session.begin():
        user = await session.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.deleted_at is not None:
            user.deleted_at = None
            user.updated_at = datetime.now(timezone.utc)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)

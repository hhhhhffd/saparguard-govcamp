"""FastAPI dependencies shared by page and JSON routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.database.models import AppUser, UserRole


def current_user(request: Request) -> AppUser:
    user = getattr(request.state, "user", None)
    if not isinstance(user, AppUser):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_role(*roles: UserRole) -> Callable[[Request], AppUser]:
    allowed = {role.value for role in roles}

    def dependency(request: Request) -> AppUser:
        user = current_user(request)
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


require_worker = require_role(UserRole.WORKER, UserRole.ADMIN)
require_admin = require_role(UserRole.ADMIN)

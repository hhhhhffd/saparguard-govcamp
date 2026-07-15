from __future__ import annotations

from datetime import datetime, timedelta, timezone
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth.dependencies import require_admin, require_worker
from app.auth.google import google_auth_available, initialize_google_provider
from app.auth.service import (
    AuthenticationError,
    MIN_PASSWORD_LENGTH,
    bootstrap_default_admin,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_and_validate_email,
    verify_password,
)
from app.core.config import settings
from app.database.models import AppUser, Complaint, UserRole
from app.web.routes.admin import user_update
from app.web.routes.complaints import complaint_detail


def app_user(user_id: int, role: UserRole = UserRole.CITIZEN) -> AppUser:
    now = datetime.now(timezone.utc)
    return AppUser(
        id=user_id,
        email=f"user{user_id}@example.test",
        normalized_email=f"user{user_id}@example.test",
        password_hash=None,
        google_account_id=None,
        role=role.value,
        is_active=True,
        registration_source="local",
        created_at=now,
        updated_at=now,
        last_login_at=None,
        deleted_at=None,
    )


def request_for(user: AppUser) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.user = user
    return request


def test_short_password_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        hash_password("x" * (MIN_PASSWORD_LENGTH - 1))


def test_accepted_password_is_bcrypt_hashed_without_plaintext() -> None:
    password = "sufficient-password"
    password_hash = hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$2")
    assert verify_password(password, password_hash)
    assert not verify_password("incorrect-password", password_hash)


def test_jwt_is_created_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    token = create_access_token(app_user(17))

    assert decode_access_token(token) == 17


def test_expired_jwt_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    token = jwt.encode(
        {"sub": "17", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_role_dependencies_reject_insufficient_role() -> None:
    citizen_request = request_for(app_user(1))
    worker_request = request_for(app_user(2, UserRole.WORKER))

    with pytest.raises(HTTPException, match="403"):
        require_worker(citizen_request)
    with pytest.raises(HTTPException, match="403"):
        require_admin(worker_request)


def test_google_fallback_is_disabled_when_configuration_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "google_redirect_uri", None)

    initialize_google_provider()

    assert not google_auth_available()


def test_login_shows_localized_google_fallback() -> None:
    from app.main import app

    response = TestClient(app).get("/auth/login")

    assert response.status_code == 200
    assert "😢 Не істемейді..." in response.text
    assert "accounts.google.com/gsi/client" not in response.text


def test_login_uses_official_google_identity_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app
    from app.web.routes import auth

    monkeypatch.setattr(auth, "google_auth_available", lambda: True)
    monkeypatch.setattr(settings, "google_client_id", "client-id.apps.googleusercontent.com")

    response = TestClient(app).get("/auth/login")

    assert response.status_code == 200
    assert "accounts.google.com/gsi/client" in response.text
    assert "data-google-sign-in" in response.text
    assert 'href="/auth/google"' not in response.text


def test_account_route_requires_sign_in() -> None:
    from app.main import app

    response = TestClient(app).get("/account", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


@pytest.mark.parametrize("role", [UserRole.CITIZEN, UserRole.WORKER, UserRole.ADMIN])
def test_authenticated_account_route_and_navigation_use_canonical_path(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    user = app_user(1, role)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
            return False

        async def get(self, model: object, identity: int) -> AppUser | None:
            return user if identity == user.id else None

    monkeypatch.setattr(main, "SessionFactory", lambda: Session())
    client = TestClient(main.app)
    client.cookies.set(settings.jwt_cookie_name, create_access_token(user))

    response = client.get("/account")

    assert response.status_code == 200
    assert 'href="/account"' in response.text
    assert "/auth/account" not in response.text

    legacy_response = client.get("/auth/account", follow_redirects=False)
    assert legacy_response.status_code == 303
    assert legacy_response.headers["location"] == "/account"


@pytest.mark.asyncio
async def test_citizen_cannot_open_another_users_complaint() -> None:
    complaint = Complaint(
        id=8,
        author_id=1,
        subject="subject",
        description="description",
        location_text=None,
        status="new",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        status_changed_by_id=None,
    )

    class Session:
        async def get(self, model: object, identity: int) -> Complaint | None:
            return complaint

    with pytest.raises(HTTPException, match="403"):
        await complaint_detail(8, request_for(app_user(2)), app_user(2), Session())


@pytest.mark.asyncio
async def test_admin_can_assign_worker_role() -> None:
    managed_user = app_user(2)

    class Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
            return False

    class Session:
        def __init__(self) -> None:
            self.scalar_calls = 0

        def begin(self) -> Transaction:
            return Transaction()

        async def get(self, model: object, identity: int) -> AppUser | None:
            return managed_user

        async def scalar(self, statement: object) -> int:
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else 1

    response = await user_update(
        2,
        request_for(app_user(1, UserRole.ADMIN)),
        "worker@example.com",
        UserRole.WORKER.value,
        True,
        None,
        False,
        False,
        app_user(1, UserRole.ADMIN),
        Session(),
    )

    assert response.status_code == 303
    assert managed_user.role == UserRole.WORKER.value


@pytest.mark.parametrize("email", ["abc", "test@", "", "   "])
def test_invalid_email_is_rejected(email: str) -> None:
    with pytest.raises(AuthenticationError, match="корректный email"):
        normalize_and_validate_email(email)


def test_email_is_trimmed_and_casefolded_for_uniqueness() -> None:
    display_email, normalized_email = normalize_and_validate_email("  Test@Example.COM ")

    assert display_email == "Test@example.com"
    assert normalized_email == "test@example.com"


@pytest.mark.asyncio
async def test_bootstrap_rejects_conflicting_citizen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(settings, "default_admin_password", "sufficient-password")
    existing = app_user(1, UserRole.CITIZEN)

    class Session:
        async def scalar(self, statement: object) -> AppUser:
            return existing

    with pytest.raises(RuntimeError, match="DEFAULT_ADMIN_EMAIL conflicts"):
        await bootstrap_default_admin(Session())

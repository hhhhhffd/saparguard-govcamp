"""Google OIDC provider setup kept optional for local-only deployments."""

from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from app.core.config import settings

logger = logging.getLogger(__name__)

_google_client: StarletteOAuth2App | None = None
_google_initialization_error: str | None = None


def google_auth_available() -> bool:
    return _google_client is not None


def initialize_google_provider() -> None:
    """Register Google only when all configuration is present and valid."""
    global _google_client, _google_initialization_error
    _google_client = None
    _google_initialization_error = None
    values = (
        settings.google_client_id,
        settings.google_client_secret,
        settings.google_redirect_uri,
    )
    if not any(values):
        return
    if not all(values):
        _google_initialization_error = "Google OAuth configuration is incomplete"
        logger.warning(_google_initialization_error)
        return
    try:
        oauth = OAuth()
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _google_client = oauth.create_client("google")
    except Exception:
        _google_initialization_error = "Google OAuth provider initialization failed"
        logger.exception(_google_initialization_error)


def google_client() -> StarletteOAuth2App | None:
    return _google_client

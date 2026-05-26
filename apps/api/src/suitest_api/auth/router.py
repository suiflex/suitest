"""Aggregate auth router: login/logout + register + users + Google OAuth."""

from fastapi import APIRouter

from suitest_api.auth.manager import (
    auth_backend,
    fastapi_users,
    google_oauth_client,
)
from suitest_api.auth.schemas import UserCreate, UserRead, UserUpdate
from suitest_api.settings import get_settings

_settings = get_settings()

router = APIRouter()

router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

router.include_router(
    fastapi_users.get_oauth_router(
        google_oauth_client,
        auth_backend,
        _settings.auth_secret,
        associate_by_email=True,
        is_verified_by_default=True,
    ),
    prefix="/auth/google",
    tags=["auth"],
)

"""Wire FastAPI-Users routers + Google OAuth router."""

from fastapi import APIRouter
from httpx_oauth.clients.google import GoogleOAuth2

from suitest_api.auth.manager import auth_backend, fastapi_users
from suitest_api.auth.schemas import UserCreate, UserRead, UserUpdate
from suitest_api.settings import get_settings

_settings = get_settings()

router = APIRouter()

router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/cookie",
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


google_oauth_client = GoogleOAuth2(
    client_id=_settings.oauth_google_client_id or "unset",
    client_secret=_settings.oauth_google_client_secret or "unset",
)

router.include_router(
    fastapi_users.get_oauth_router(
        google_oauth_client,
        auth_backend,
        _settings.auth_secret,
        redirect_url=f"{_settings.web_url}/dashboard",
        associate_by_email=True,
        is_verified_by_default=True,
    ),
    prefix="/auth/google",
    tags=["auth"],
)

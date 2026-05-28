"""Process-level settings sourced from environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level config for the API process."""

    model_config = SettingsConfigDict(
        env_prefix="SUITEST_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=4000)
    web_url: str = Field(default="http://localhost:3000")
    api_url: str = Field(default="http://localhost:4000")
    log_level: str = Field(default="INFO")

    # Auth / OAuth — required for FastAPI-Users + Google OAuth
    auth_secret: str = Field(default="dev-secret-change-me")
    database_url: str = Field(default="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest")
    oauth_google_client_id: str = Field(default="")
    oauth_google_client_secret: str = Field(default="")

    # Session cookie security. ``False`` for local dev over plain HTTP; production
    # behind HTTPS MUST set ``SUITEST_COOKIE_SECURE=true`` so the cookie is only
    # sent over TLS. Read by :mod:`suitest_api.auth.manager` when constructing
    # the FastAPI-Users :class:`CookieTransport`.
    cookie_secure: bool = Field(default=False)


def get_settings() -> Settings:
    """Return a fresh Settings instance (env-resolved)."""
    return Settings()

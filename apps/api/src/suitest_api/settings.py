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
    superadmin_email: str = Field(default="")
    superadmin_password: str = Field(default="", repr=False)
    superadmin_workspace_name: str = Field(default="Default Workspace")
    invite_ttl_hours: int = Field(default=168)

    # Session cookie security. ``False`` for local dev over plain HTTP; production
    # behind HTTPS MUST set ``SUITEST_COOKIE_SECURE=true`` so the cookie is only
    # sent over TLS. Read by :mod:`suitest_api.auth.manager` when constructing
    # the FastAPI-Users :class:`CookieTransport`.
    cookie_secure: bool = Field(default=False)

    # S3 / MinIO target for artifact downloads. The presign endpoint
    # (``GET /runs/:id/artifacts/:id``) issues against these credentials.
    # Defaults point at the docker-compose dev MinIO; production overrides
    # via env. Mirrored from :class:`RunnerSettings` so both processes can
    # share one ``SUITEST_S3_*`` set without re-declaring the same env vars.
    s3_endpoint: str = Field(default="http://localhost:9000")
    s3_bucket: str = Field(default="suitest-artifacts")
    s3_access_key: str = Field(default="minioadmin")
    s3_secret_key: str = Field(default="minioadmin")
    s3_region: str = Field(default="us-east-1")

    # Local mode (no S3): root folder ``local://`` artifact keys resolve
    # against — served by ``GET /runs/:id/artifacts/:artifact_id/raw``.
    # Must point at the same folder the runner writes to
    # (``SUITEST_ARTIFACTS_DIR``). env: SUITEST_ARTIFACTS_DIR
    artifacts_dir: str = Field(default=".suitest/artifacts")


def get_settings() -> Settings:
    """Return a fresh Settings instance (env-resolved)."""
    return Settings()

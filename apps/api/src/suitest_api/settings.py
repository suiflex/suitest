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


def get_settings() -> Settings:
    """Return a fresh Settings instance (env-resolved)."""
    return Settings()

"""DB-scoped settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DbSettings(BaseSettings):
    """Database connection config."""

    model_config = SettingsConfigDict(env_prefix="SUITEST_", extra="ignore")

    database_url: str = Field(default="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest")
    echo_sql: bool = Field(default=False)
    pool_size: int = Field(default=5)
    max_overflow: int = Field(default=10)

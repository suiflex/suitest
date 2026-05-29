"""Process-level settings sourced from environment for the ARQ worker.

The worker shares ``SUITEST_DATABASE_URL`` with :mod:`suitest_api` (one DB
config across the platform) and ``SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE`` with
:mod:`suitest_mcp.pool` (the pool reads it directly from env via
:func:`suitest_mcp.pool._resolve_workspace_cap` — we expose it here so the
worker can log the resolved value at boot, and so tests can assert the wiring).

All other knobs use the ``SUITEST_RUNNER_`` prefix to avoid colliding with API
settings even when both processes are launched from the same .env file.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunnerSettings(BaseSettings):
    """Top-level config for the ARQ worker process."""

    model_config = SettingsConfigDict(
        env_prefix="SUITEST_RUNNER_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # Redis: ``SUITEST_RUNNER_REDIS_URL`` falls back to ``SUITEST_REDIS_URL`` so
    # the API + worker can share one Redis URL via a single env var when
    # deployed side-by-side.
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("SUITEST_RUNNER_REDIS_URL", "SUITEST_REDIS_URL"),
    )

    # Database: shared with apps/api. Honor the unprefixed SUITEST_DATABASE_URL
    # so a single .env keeps both processes in sync.
    database_url: str = Field(
        default="postgresql+asyncpg://suitest:suitest@localhost:5432/suitest",
        validation_alias=AliasChoices("SUITEST_RUNNER_DATABASE_URL", "SUITEST_DATABASE_URL"),
    )

    # Concurrency: how many jobs ARQ runs in parallel per worker process.
    max_jobs_concurrent: int = Field(default=4, ge=1)

    # Per-job wall clock. ARQ kills the coroutine when the budget is exhausted.
    job_timeout_seconds: int = Field(default=300, ge=1)

    # Workspace-wide MCP session cap. Read from SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE
    # so the worker + suitest_mcp.pool see the same value without a second env var.
    mcp_max_sessions_per_workspace: int = Field(
        default=16,
        ge=1,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_MCP_MAX_SESSIONS_PER_WORKSPACE",
            "SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE",
        ),
    )

    # MCP pool queue budget: how long an acquire() may wait for a free slot.
    mcp_queue_timeout_seconds: float = Field(default=30.0, gt=0.0)

    # ARQ queue name + result retention.
    queue_name: str = Field(default="suitest:runs")
    keep_result_seconds: int = Field(default=3600, ge=0)


def get_settings() -> RunnerSettings:
    """Return a fresh RunnerSettings instance (env-resolved)."""
    return RunnerSettings()

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
    # ``SUITEST_RUNNER_CONCURRENCY`` is the canonical knob (Task 21). The legacy
    # ``SUITEST_RUNNER_MAX_JOBS_CONCURRENT`` env name remains a valid alias so
    # existing deployments don't break on upgrade.
    max_jobs_concurrent: int = Field(
        default=4,
        ge=1,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_CONCURRENCY",
            "SUITEST_RUNNER_MAX_JOBS_CONCURRENT",
        ),
    )

    # Per-job ARQ retry budget. ARQ re-enqueues the coroutine up to this many
    # times on transient failure before the job is marked failed.
    max_retries: int = Field(default=2, ge=0)

    # Per-job wall clock. ARQ kills the coroutine when the budget is exhausted.
    # Default raised to 1800s (30min) for end-to-end suites; per-step timeouts
    # are enforced at the MCP provider level (``call_timeout_seconds``).
    job_timeout_seconds: int = Field(default=1800, ge=1)

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
    # Honors the unprefixed ``SUITEST_MCP_QUEUE_TIMEOUT_SECONDS`` so the runner
    # and the cap layer share one source of truth (mirroring the
    # ``mcp_max_sessions_per_workspace`` alias above).
    mcp_queue_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_MCP_QUEUE_TIMEOUT_SECONDS",
            "SUITEST_MCP_QUEUE_TIMEOUT_SECONDS",
        ),
    )

    # ARQ queue name + result retention.
    queue_name: str = Field(default="suitest:runs")
    keep_result_seconds: int = Field(default=3600, ge=0)

    # Evidence recording mode. OFF by default so normal CI/test execution stays
    # full-speed. When enabled, the runner inserts a small pause between steps so
    # the session video (recorded by the playwright-mcp Node subprocess) is long
    # enough to follow step-by-step, and downstream evidence (per-step
    # screenshots + timestamps) reads as a proper timeline. Honors the unprefixed
    # ``SUITEST_EVIDENCE_RECORDING`` so the lifecycle CLI and the worker agree.
    evidence_recording: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_EVIDENCE_RECORDING",
            "SUITEST_EVIDENCE_RECORDING",
        ),
    )
    # Pause inserted AFTER each step when evidence recording is on (milliseconds).
    # Only applied in evidence mode — it never affects default execution.
    evidence_pause_ms: int = Field(
        default=700,
        ge=0,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_EVIDENCE_PAUSE_MS",
            "SUITEST_EVIDENCE_PAUSE_MS",
        ),
    )

    # S3 / MinIO target for artifact upload. Defaults point at a local MinIO
    # (the docker-compose dev stack). Production deploys override the endpoint
    # with the real bucket URL. Credentials default to the well-known MinIO
    # dev defaults — production MUST override via env.
    s3_endpoint: str = Field(
        default="http://localhost:9000",
        validation_alias=AliasChoices("SUITEST_RUNNER_S3_ENDPOINT", "SUITEST_S3_ENDPOINT"),
    )
    s3_bucket: str = Field(
        default="suitest-artifacts",
        validation_alias=AliasChoices("SUITEST_RUNNER_S3_BUCKET", "SUITEST_S3_BUCKET"),
    )
    s3_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("SUITEST_RUNNER_S3_ACCESS_KEY", "SUITEST_S3_ACCESS_KEY"),
    )
    s3_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("SUITEST_RUNNER_S3_SECRET_KEY", "SUITEST_S3_SECRET_KEY"),
    )
    s3_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("SUITEST_RUNNER_S3_REGION", "SUITEST_S3_REGION"),
    )

    # M4-32 / M4-29: cold-storage bucket for archived audit logs + workspace
    # export tarballs. Separate from the artifact bucket so retention /
    # lifecycle policies can differ (archives live longer, cheaper tier).
    s3_archive_bucket: str = Field(
        default="suitest-archive",
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_S3_ARCHIVE_BUCKET", "SUITEST_S3_ARCHIVE_BUCKET"
        ),
    )

    # M4-32: hot-table retention for audit_logs. Rows older than this are moved
    # to cold storage (compressed JSONL per workspace per month) by the daily
    # ``rotate_audit_logs`` cron and deleted from the DB.
    audit_log_retention_days: int = Field(
        default=365,
        ge=1,
        validation_alias=AliasChoices(
            "SUITEST_RUNNER_AUDIT_LOG_RETENTION_DAYS",
            "SUITEST_AUDIT_LOG_RETENTION_DAYS",
        ),
    )


def get_settings() -> RunnerSettings:
    """Return a fresh RunnerSettings instance (env-resolved)."""
    return RunnerSettings()

"""Tests for :class:`suitest_runner.settings.RunnerSettings`.

Asserts:
* defaults are stable so omitting env vars yields a known config;
* prefixed env vars (``SUITEST_RUNNER_*``) override defaults;
* the database URL falls back to the shared ``SUITEST_DATABASE_URL`` so the
  worker doesn't need its own copy when deployed alongside ``apps/api``;
* the MCP workspace cap honors the unprefixed
  ``SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE`` so :mod:`suitest_mcp.pool` and the
  worker see the same value.
"""

from __future__ import annotations

import pytest
from suitest_runner.settings import RunnerSettings, get_settings


@pytest.mark.usefixtures("clean_runner_env")
def test_defaults_when_no_env() -> None:
    """No env → documented defaults."""
    settings = RunnerSettings()
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.max_jobs_concurrent == 4
    assert settings.max_retries == 2
    assert settings.job_timeout_seconds == 1800
    assert settings.mcp_max_sessions_per_workspace == 16
    assert settings.mcp_queue_timeout_seconds == 30.0
    assert settings.queue_name == "suitest:runs"


@pytest.mark.usefixtures("clean_runner_env")
def test_prefixed_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SUITEST_RUNNER_*`` env vars override defaults."""
    monkeypatch.setenv("SUITEST_RUNNER_REDIS_URL", "redis://h:1/2")
    monkeypatch.setenv("SUITEST_RUNNER_MAX_JOBS_CONCURRENT", "8")
    monkeypatch.setenv("SUITEST_RUNNER_JOB_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("SUITEST_RUNNER_MAX_RETRIES", "5")
    monkeypatch.setenv("SUITEST_RUNNER_QUEUE_NAME", "suitest:runs:custom")
    settings = RunnerSettings()
    assert settings.redis_url == "redis://h:1/2"
    assert settings.max_jobs_concurrent == 8
    assert settings.job_timeout_seconds == 600
    assert settings.max_retries == 5
    assert settings.queue_name == "suitest:runs:custom"


@pytest.mark.usefixtures("clean_runner_env")
def test_concurrency_alias_overrides_max_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SUITEST_RUNNER_CONCURRENCY`` is the canonical alias for max_jobs_concurrent."""
    monkeypatch.setenv("SUITEST_RUNNER_CONCURRENCY", "12")
    assert RunnerSettings().max_jobs_concurrent == 12


@pytest.mark.usefixtures("clean_runner_env")
def test_database_url_falls_back_to_shared_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When only ``SUITEST_DATABASE_URL`` is set the worker picks it up too."""
    shared = "postgresql+asyncpg://u:p@db:5432/suitest"
    monkeypatch.setenv("SUITEST_DATABASE_URL", shared)
    assert RunnerSettings().database_url == shared


@pytest.mark.usefixtures("clean_runner_env")
def test_runner_prefixed_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SUITEST_RUNNER_DATABASE_URL`` overrides the shared default."""
    monkeypatch.setenv("SUITEST_DATABASE_URL", "postgresql+asyncpg://shared/x")
    monkeypatch.setenv("SUITEST_RUNNER_DATABASE_URL", "postgresql+asyncpg://runner/y")
    assert RunnerSettings().database_url == "postgresql+asyncpg://runner/y"


@pytest.mark.usefixtures("clean_runner_env")
def test_mcp_workspace_cap_reads_shared_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The runner reads ``SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE`` so it agrees
    with the pool's own resolver (see :mod:`suitest_mcp.pool`)."""
    monkeypatch.setenv("SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE", "32")
    assert RunnerSettings().mcp_max_sessions_per_workspace == 32


@pytest.mark.usefixtures("clean_runner_env")
def test_mcp_queue_timeout_reads_shared_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SUITEST_MCP_QUEUE_TIMEOUT_SECONDS`` (unprefixed) flows into the worker."""
    monkeypatch.setenv("SUITEST_MCP_QUEUE_TIMEOUT_SECONDS", "5.5")
    assert RunnerSettings().mcp_queue_timeout_seconds == pytest.approx(5.5)


@pytest.mark.usefixtures("clean_runner_env")
def test_get_settings_returns_fresh_instance() -> None:
    """``get_settings`` is a fresh-instance factory, not a cached singleton."""
    a = get_settings()
    b = get_settings()
    assert a is not b
    assert a.model_dump() == b.model_dump()

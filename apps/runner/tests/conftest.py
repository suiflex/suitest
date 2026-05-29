"""Shared fixtures for the suitest_runner test suite.

Two goals:
* Keep OTel disabled by default so the BatchSpanProcessor doesn't spin up a
  background thread trying to flush to ``localhost:4318`` in CI (same pattern
  as ``apps/api/tests/conftest.py``).
* Provide an in-memory Redis stub via :mod:`fakeredis` so the worker boot /
  enqueue tests run without a live broker.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from redis.asyncio import Redis as AsyncRedis

# Disable OpenTelemetry exporter by default in tests — guards against a
# BatchSpanProcessor thread leaking out of import-time setup.
os.environ.setdefault("SUITEST_OTEL_DISABLED", "true")


@pytest.fixture()
def clean_runner_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip ``SUITEST_*`` env so settings tests see defaults.

    Tests that want to assert env-driven values opt in by re-setting the
    relevant variables via :meth:`monkeypatch.setenv` after this fixture runs.
    """
    for key in list(os.environ):
        if key.startswith("SUITEST_"):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest_asyncio.fixture()
async def fake_redis() -> AsyncIterator[AsyncRedis]:
    """In-memory async Redis stub for worker / enqueue tests."""
    client = fake_aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()

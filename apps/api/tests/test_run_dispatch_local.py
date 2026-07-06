"""Unit tests for the run dispatcher seam (Task 4).

Verifies that ``dispatch_run`` skips ARQ in local mode and enqueues in server
mode, without any DB or network involvement.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from suitest_api.deps.run_dispatch import dispatch_run


@dataclass
class _FakeJob:
    job_id: str


class _SpyArq:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def enqueue_job(
        self, name: str, *args: object, _queue_name: str | None = None
    ) -> object:
        self.calls.append((name, args[0]))
        return _FakeJob(job_id=f"job-{args[0]}")


@pytest.mark.asyncio
async def test_local_mode_does_not_enqueue() -> None:
    arq = _SpyArq()
    result = await dispatch_run(
        mode="local", arq=arq, run_id="run-1", queue_name="suitest:runs"
    )
    assert arq.calls == []  # local: supervisor picks it up from QUEUED
    assert result is None


@pytest.mark.asyncio
async def test_server_mode_enqueues() -> None:
    arq = _SpyArq()
    result = await dispatch_run(
        mode="server", arq=arq, run_id="run-1", queue_name="suitest:runs"
    )
    assert arq.calls == [("run_test_case", "run-1")]
    assert result == "job-run-1"

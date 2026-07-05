"""No-op pub/sub for local mode — satisfies the ``publish``/``incr`` protocol
that :func:`suitest_runner.jobs.run_test_case.run_test_case` and
:class:`suitest_mcp...McpInvoker` consume, without a Redis broker.

Live-log fan-out is dropped (the local dashboard reads final state from the DB,
not the live channel). Counters are kept in-process for parity with callers that
read them back.
"""

from __future__ import annotations


class NullPublisher:
    """Drop-in for the redis client passed as ``ctx["redis"]`` in local mode."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def publish(self, channel: str, message: str | bytes) -> int:
        # ponytail: live log fan-out intentionally dropped in local mode.
        return 0

    async def incr(self, name: str) -> int:
        self._counts[name] = self._counts.get(name, 0) + 1
        return self._counts[name]

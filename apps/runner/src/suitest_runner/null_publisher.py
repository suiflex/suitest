"""No-op pub/sub for local mode — satisfies the ``publish``/``incr`` protocol
that :func:`suitest_runner.jobs.run_test_case.run_test_case` and
:class:`suitest_mcp...McpInvoker` consume, without a Redis broker.

Live-log fan-out is dropped (the local dashboard reads final state from the DB,
not the live channel). Counters are kept in-process for parity with callers that
read them back.
"""

from __future__ import annotations

from suitest_mcp.invoker import NullPublisher

__all__ = ["NullPublisher"]

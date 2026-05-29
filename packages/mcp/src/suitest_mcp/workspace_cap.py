"""Workspace-level fair-queue session cap (M1c Task 21).

The connection pool in :mod:`suitest_mcp.pool` already enforces a soft
workspace cap via a busy-poll on ``McpPool._workspace_live``. That model is
fine for the small-N steady-state but degrades in two scenarios:

1. **Cross-provider bursts.** When 8 steps in 8 different providers fire at
   once, each provider pool sees a single acquire and dispatches immediately —
   the workspace-cap check only fires AFTER the provider pool grants the slot,
   making it racy under contention.
2. **Backpressure fairness.** Busy-poll on a 50ms loop does not preserve FIFO
   admission order; whichever coroutine wakes first wins. Under stress this
   produces starvation patterns where some workspaces' jobs always queue and
   others always pass.

:class:`WorkspacePoolCap` lives *above* the per-provider pool. The runner
wraps every ``invoker.invoke`` with ``async with cap.reserve(workspace_id,
timeout=...)``. Inside the reservation the invoker is free to acquire from
:class:`McpPool` and call the tool; the reservation decrements on exit and
notifies the condition so the next FIFO waiter wakes.

Key design points:

* **Asyncio.Condition with explicit lock release while waiting.** Python's
  ``Condition.wait()`` releases its underlying lock for the duration of the
  wait and re-acquires before returning — so multiple waiters can serialise
  through the same condition without livelock.
* **Per-workspace counter map** keyed on ``workspace_id``. We never garbage
  collect entries; the dict footprint is bounded by the number of
  *currently-active* workspaces over the process lifetime (the count drops to
  zero on exit but the key remains, which is fine for typical N≤1000
  workspaces per worker).
* **Deadline-aware wait.** The reservation acquires a monotonic deadline at
  entry. Each ``wait()`` call uses ``asyncio.wait_for`` bounded by the
  remaining budget. On timeout we raise :class:`McpPoolExhausted` with a
  message naming the workspace + cap so the runner's step-error path can
  surface ``reason=POOL_EXHAUSTED`` cleanly.
* **notify_all on release.** All waiters are woken so each can re-check the
  counter; only one will succeed in incrementing (the loop is guarded by the
  condition) and the rest wait again. This is correct (no lost wakeups) and
  simpler than the more efficient ``notify(n)`` accounting.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from suitest_mcp.errors import McpPoolExhausted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class WorkspacePoolCap:
    """Per-workspace fair-queue cap on concurrent MCP sessions.

    Args:
        max_per_workspace: Maximum number of concurrent reservations a single
            ``workspace_id`` may hold. Reservations queue (FIFO via
            :class:`asyncio.Condition`) once the cap is reached.
        queue_timeout_seconds: Default deadline for :meth:`reserve` callers
            that don't pass an explicit ``timeout``. Exposed so the invoker
            can read one canonical setting from the cap rather than carrying
            its own copy.
    """

    def __init__(
        self,
        *,
        max_per_workspace: int,
        queue_timeout_seconds: float = 30.0,
    ) -> None:
        if max_per_workspace < 1:
            msg = f"max_per_workspace must be >= 1, got {max_per_workspace}"
            raise ValueError(msg)
        self.max = max_per_workspace
        self.queue_timeout_seconds = queue_timeout_seconds
        self._counts: dict[str, int] = defaultdict(int)
        self._cond = asyncio.Condition()

    def live(self, workspace_id: str) -> int:
        """Return the current reservation count for ``workspace_id`` (no lock).

        Snapshot read used by tests + observability — callers tolerate a
        slightly stale value because the only consumer (peak-tracking in
        stress tests) wraps the read inside :meth:`reserve` where the
        counter is already pinned for the lifetime of the context.
        """
        return self._counts[workspace_id]

    @asynccontextmanager
    async def reserve(
        self,
        workspace_id: str,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> AsyncIterator[None]:
        """Reserve one workspace slot for the duration of the context.

        Blocks (cooperatively) until the workspace's concurrent count is
        below :attr:`max` or the ``timeout`` budget is exhausted. The slot
        is released + ``notify_all`` fires on context exit, even when the
        wrapped block raises — so :class:`McpToolFailed` / cancellation
        don't leak a reservation.

        Raises:
            McpPoolExhausted: ``timeout`` elapsed while at cap.
        """
        budget = self.queue_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + budget
        async with self._cond:
            while self._counts[workspace_id] >= self.max:
                wait_time = deadline - time.monotonic()
                if wait_time <= 0:
                    raise McpPoolExhausted(
                        f"workspace {workspace_id} session cap {self.max} reached"
                    )
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=wait_time)
                except TimeoutError as exc:
                    raise McpPoolExhausted(
                        f"workspace {workspace_id} queue timeout after {budget:.1f}s"
                    ) from exc
            self._counts[workspace_id] += 1
        try:
            yield
        finally:
            async with self._cond:
                self._counts[workspace_id] -= 1
                # All waiters wake — the loop above re-checks the counter so
                # only the first FIFO admitter advances; the rest re-wait.
                self._cond.notify_all()

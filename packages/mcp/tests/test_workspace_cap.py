"""WorkspacePoolCap fair-queue stress tests (M1c Task 21).

Drives :class:`WorkspacePoolCap` in isolation — no MCP session, no pool — so
we can assert the *queue* semantics without coupling to the stdio mock. Four
tests cover the contract:

* :func:`test_reserve_decrements_on_exit` — counter returns to baseline.
* :func:`test_blocks_when_at_cap_releases_on_completion` — a waiter wakes the
  instant a holder exits.
* :func:`test_raises_pool_exhausted_on_timeout` — deadline path raises a
  :class:`McpPoolExhausted` (so the runner translates to ``POOL_EXHAUSTED``).
* :func:`test_concurrent_8_throttled_to_max_4` — 8 coroutines hammer a cap of
  4; the test tracks ``live`` peak via an in-context atomic counter and
  asserts the workspace never exceeded the cap. This is the headline
  invariant the entire Task 21 design exists to enforce.
"""

from __future__ import annotations

import asyncio

import pytest
from suitest_mcp.errors import McpPoolExhausted
from suitest_mcp.workspace_cap import WorkspacePoolCap

pytestmark = pytest.mark.asyncio


async def test_reserve_decrements_on_exit() -> None:
    """One reservation cycle leaves the workspace count at zero."""
    cap = WorkspacePoolCap(max_per_workspace=2)
    assert cap.live("ws-a") == 0
    async with cap.reserve("ws-a", timeout=1.0):
        assert cap.live("ws-a") == 1
    assert cap.live("ws-a") == 0


async def test_reserve_decrements_on_exception() -> None:
    """Slot is released even if the wrapped block raises."""
    cap = WorkspacePoolCap(max_per_workspace=1)
    with pytest.raises(RuntimeError, match="boom"):
        async with cap.reserve("ws-a", timeout=1.0):
            assert cap.live("ws-a") == 1
            raise RuntimeError("boom")
    assert cap.live("ws-a") == 0


async def test_blocks_when_at_cap_releases_on_completion() -> None:
    """A second waiter unblocks the moment the first holder exits."""
    cap = WorkspacePoolCap(max_per_workspace=1)
    holder_entered = asyncio.Event()
    waiter_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder() -> None:
        async with cap.reserve("ws-a", timeout=5.0):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter() -> None:
        async with cap.reserve("ws-a", timeout=5.0):
            waiter_entered.set()

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()
    waiter_task = asyncio.create_task(_waiter())
    # Give the waiter a chance to actually attempt entry; assert it's still
    # blocked while the holder is in.
    await asyncio.sleep(0.05)
    assert not waiter_entered.is_set()
    assert cap.live("ws-a") == 1

    release_holder.set()
    await asyncio.wait_for(waiter_task, timeout=1.0)
    assert waiter_entered.is_set()
    await holder_task
    assert cap.live("ws-a") == 0


async def test_raises_pool_exhausted_on_timeout() -> None:
    """A waiter that exceeds its budget raises McpPoolExhausted."""
    cap = WorkspacePoolCap(max_per_workspace=1)
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder() -> None:
        async with cap.reserve("ws-a", timeout=5.0):
            holder_entered.set()
            await release_holder.wait()

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    try:
        with pytest.raises(McpPoolExhausted) as exc_info:
            async with cap.reserve("ws-a", timeout=0.05):
                pytest.fail("waiter must not enter — cap was full")
        assert "ws-a" in str(exc_info.value)
        assert exc_info.value.code == "MCP_POOL_EXHAUSTED"
    finally:
        release_holder.set()
        await holder_task


async def test_other_workspace_unaffected_by_full_cap() -> None:
    """A full ws-a cap must not block ws-b reservations (cap is per-workspace)."""
    cap = WorkspacePoolCap(max_per_workspace=1)
    held = asyncio.Event()
    release = asyncio.Event()

    async def _hold_a() -> None:
        async with cap.reserve("ws-a", timeout=5.0):
            held.set()
            await release.wait()

    holder = asyncio.create_task(_hold_a())
    await held.wait()

    # ws-b reservation completes immediately while ws-a is at cap.
    async with cap.reserve("ws-b", timeout=0.1):
        assert cap.live("ws-b") == 1
        assert cap.live("ws-a") == 1
    assert cap.live("ws-b") == 0

    release.set()
    await holder


async def test_concurrent_8_throttled_to_max_4() -> None:
    """Headline stress test: 8 parallel reservations, cap=4 → peak live ≤ 4.

    Each coroutine increments a peak tracker INSIDE the cap context (so the
    counter only reflects coroutines that have actually been admitted), and
    sleeps a tiny amount to maximise overlap. The cap's correctness is
    asserted via the peak: if any moment had >4 coroutines inside, the cap is
    broken.
    """
    cap = WorkspacePoolCap(max_per_workspace=4)
    live = 0
    peak = 0
    lock = asyncio.Lock()
    admitted = 0

    async def _worker(i: int) -> int:
        nonlocal live, peak, admitted
        async with cap.reserve("ws-a", timeout=5.0):
            async with lock:
                live += 1
                admitted += 1
                if live > peak:
                    peak = live
            # Stagger so multiple coroutines overlap inside the cap.
            await asyncio.sleep(0.02)
            async with lock:
                live -= 1
        return i

    results = await asyncio.gather(*(_worker(i) for i in range(8)))
    assert sorted(results) == list(range(8))
    assert admitted == 8
    assert peak <= 4, f"workspace cap broken — peak live count was {peak}"
    assert peak >= 1
    assert cap.live("ws-a") == 0


async def test_invalid_max_per_workspace_raises() -> None:
    """Guard rail: zero/negative cap is a programmer bug — fail loud."""
    with pytest.raises(ValueError, match="max_per_workspace"):
        WorkspacePoolCap(max_per_workspace=0)

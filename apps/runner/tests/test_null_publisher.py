import pytest
from suitest_runner.null_publisher import NullPublisher


@pytest.mark.asyncio
async def test_publish_returns_zero_and_swallows() -> None:
    pub = NullPublisher()
    assert await pub.publish("run:123", b"payload") == 0


@pytest.mark.asyncio
async def test_incr_counts_in_memory() -> None:
    pub = NullPublisher()
    assert await pub.incr("runs_started") == 1
    assert await pub.incr("runs_started") == 2

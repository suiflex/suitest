import pytest

from suitest_runner import local_supervisor


@pytest.mark.asyncio
async def test_drain_once_runs_each_queued_run(monkeypatch) -> None:
    executed: list[str] = []

    async def fake_run_test_case(ctx: dict[str, object], run_id: str) -> dict[str, object]:
        executed.append(run_id)
        return {"ok": True}

    async def fake_next_queued(session_factory: object) -> list[str]:
        return ["run-a", "run-b"]

    monkeypatch.setattr(local_supervisor, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(local_supervisor, "_next_queued_run_ids", fake_next_queued)

    ctx = {"session_factory": object()}
    await local_supervisor.drain_once(ctx)

    assert executed == ["run-a", "run-b"]


@pytest.mark.asyncio
async def test_drain_once_poll_error_does_not_propagate(monkeypatch) -> None:
    """_next_queued_run_ids raising must not crash the loop."""

    async def fake_next_queued(session_factory: object) -> list[str]:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(local_supervisor, "_next_queued_run_ids", fake_next_queued)

    ctx = {"session_factory": object()}
    # must not raise
    await local_supervisor.drain_once(ctx)


@pytest.mark.asyncio
async def test_drain_once_run_error_continues_remaining(monkeypatch) -> None:
    """run_test_case raising for one run_id must not block subsequent ones."""
    executed: list[str] = []

    async def fake_run_test_case(ctx: dict[str, object], run_id: str) -> dict[str, object]:
        if run_id == "run-a":
            raise RuntimeError("runner exploded")
        executed.append(run_id)
        return {"ok": True}

    async def fake_next_queued(session_factory: object) -> list[str]:
        return ["run-a", "run-b"]

    monkeypatch.setattr(local_supervisor, "run_test_case", fake_run_test_case)
    monkeypatch.setattr(local_supervisor, "_next_queued_run_ids", fake_next_queued)

    ctx = {"session_factory": object()}
    await local_supervisor.drain_once(ctx)

    assert executed == ["run-b"]

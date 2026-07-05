import pytest

from suitest_runner.local_ctx import build_local_ctx


@pytest.mark.asyncio
async def test_build_local_ctx_has_required_keys() -> None:
    ctx: dict[str, object] = {}
    await build_local_ctx(ctx)
    try:
        for key in ("settings", "engine", "session_factory", "redis", "invoker", "registry"):
            assert key in ctx, f"missing ctx key: {key}"
        # local mode never wires the ARQ-backed defect auto-filer
        assert ctx.get("defect_auto_filer") is None
    finally:
        engine = ctx.get("engine")
        if engine is not None:
            await engine.dispose()  # type: ignore[attr-defined]

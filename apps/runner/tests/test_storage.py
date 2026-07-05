"""Storage backend selection + local disk writes (local mode)."""

import pytest


@pytest.mark.asyncio
async def test_local_storage_writes_file_and_returns_local_url(tmp_path) -> None:
    from suitest_runner.storage import LocalStorage

    storage = LocalStorage(root=tmp_path)
    url = await storage.put(
        key="runs/r1/step-1/screenshot/shot.png",
        body=b"\x89PNG-fake",
        content_type="image/png",
    )
    assert url == "local://runs/r1/step-1/screenshot/shot.png"
    written = tmp_path / "runs/r1/step-1/screenshot/shot.png"
    assert written.read_bytes() == b"\x89PNG-fake"


def test_make_storage_selects_backend(tmp_path) -> None:
    from suitest_runner.settings import RunnerSettings
    from suitest_runner.storage import LocalStorage, S3Storage, make_storage

    local = make_storage(RunnerSettings(artifacts_backend="local", artifacts_dir=str(tmp_path)))
    assert isinstance(local, LocalStorage)

    s3 = make_storage(RunnerSettings(artifacts_backend="s3"))
    assert isinstance(s3, S3Storage)

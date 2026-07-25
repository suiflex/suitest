"""read_bytes resolves local:// and file:// artifact URLs to bytes (no S3 needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from suitest_api.services import file_storage


@pytest.mark.asyncio
async def test_read_bytes_file_scheme(tmp_path: Path) -> None:
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNGdata")
    got = await file_storage.read_bytes(f"file://{p}")
    assert got == b"\x89PNGdata"


@pytest.mark.asyncio
async def test_read_bytes_local_scheme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = "uploads/ws1/abc/shot.png"
    target = tmp_path / key
    target.parent.mkdir(parents=True)
    target.write_bytes(b"localbytes")
    monkeypatch.setattr(file_storage, "local_path", lambda k: tmp_path / k)
    got = await file_storage.read_bytes(f"local://{key}")
    assert got == b"localbytes"


@pytest.mark.asyncio
async def test_read_bytes_missing_returns_none(tmp_path: Path) -> None:
    got = await file_storage.read_bytes(f"file://{tmp_path / 'nope.png'}")
    assert got is None

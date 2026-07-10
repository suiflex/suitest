"""Tests for cross-OS stdio command resolution."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from suitest_mcp.proc import resolve_command


def test_resolve_command_returns_absolute_for_path_on_disk() -> None:
    resolved = resolve_command("/bin/sh")
    assert Path(resolved).is_absolute()
    assert Path(resolved).exists()


def test_resolve_command_finds_bare_name_on_path(tmp_path: Path) -> None:
    exe = tmp_path / "faketool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{tmp_path}{os.pathsep}{old}"
    try:
        assert resolve_command("faketool") == str(exe)
    finally:
        os.environ["PATH"] = old


def test_resolve_command_returns_input_when_missing() -> None:
    # Unknown command falls through unchanged so the transport surfaces the error.
    assert resolve_command("definitely-not-a-real-binary-xyz") == (
        "definitely-not-a-real-binary-xyz"
    )

"""The white-box runner must use the project's toolchain, not Suitest's.

A project's own tests import the project's own dependencies, so running them
with Suitest's interpreter fails even when the user has everything installed.
"""

from __future__ import annotations

import sys

from suitest_lifecycle import pydeps
from suitest_lifecycle.whitebox import NodeTestAdapter, PytestAdapter, detect_adapter


def _make_venv(root):
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    return python


def test_pytest_runs_with_the_project_venv_when_present(tmp_path) -> None:
    python = _make_venv(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    adapter = detect_adapter(tmp_path)
    assert isinstance(adapter, PytestAdapter)
    assert adapter.command_for(tmp_path / "test_x.py")[0] == str(python)
    assert adapter.discover(tmp_path).command[0] == str(python)


def test_pytest_venv_is_trusted_to_carry_its_own_pytest(tmp_path, monkeypatch) -> None:
    _make_venv(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    installs: list[str] = []
    monkeypatch.setattr(pydeps, "install", lambda pkg, *_: installs.append(pkg))
    status = detect_adapter(tmp_path).ensure_runtime()
    assert status.ready is True
    assert installs == []  # never mutate the user's venv uninvited


def test_pytest_falls_back_to_suitest_interpreter_and_provisions_pytest(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    adapter = detect_adapter(tmp_path)
    assert adapter.command_for(tmp_path / "test_x.py")[0] == sys.executable
    monkeypatch.setattr(pydeps, "importable", lambda _: False)
    asked: list[str] = []
    monkeypatch.setattr(
        pydeps, "install", lambda pkg, *_: asked.append(pkg) or pydeps.DepStatus(True, "installed")
    )
    assert adapter.ensure_runtime().ready is True
    assert asked == ["pytest"]


def test_node_adapter_defers_to_npm_exec(tmp_path) -> None:
    (tmp_path / "package.json").write_text('{"devDependencies":{"vitest":"1"}}')
    adapter = detect_adapter(tmp_path)
    assert isinstance(adapter, NodeTestAdapter)
    status = adapter.ensure_runtime()
    assert status.ready is True
    assert "npm exec" in status.detail


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

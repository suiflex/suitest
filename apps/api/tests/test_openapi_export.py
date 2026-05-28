"""Tests for ``scripts/export-openapi.py``.

The export script is the heart of the CI drift gate (see
``.github/workflows/ci.yml``). These tests pin two invariants:

1. Running the script writes a parseable OpenAPI document to the chosen path.
2. Two consecutive runs produce byte-identical output (sort_keys stability),
   so any human-visible diff in CI implies a real wire-contract change.

We import the script as a module rather than spawning a subprocess so mypy can
type-check the test and the in-process FastAPI app is reused across both
assertions (cheaper and avoids ``uv run`` cold-start overhead).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "export-openapi.py"


def _load_export_module() -> ModuleType:
    """Import ``scripts/export-openapi.py`` under a synthetic module name.

    The hyphen in the filename makes a plain ``import`` impossible; importlib's
    spec-from-file-location is the canonical workaround.
    """
    spec = importlib.util.spec_from_file_location("suitest_export_openapi", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_openapi_export_writes_file(tmp_path: Path) -> None:
    """Script writes a parseable OpenAPI 3.x document with at least one path."""
    export = _load_export_module()
    output = tmp_path / "openapi.json"

    exit_code = export.main([str(output)])

    assert exit_code == 0
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["openapi"].startswith("3.")
    assert payload["info"]["title"] == "Suitest API"
    # Sanity check: routes wired in create_app must show up in the schema.
    assert "/health" in payload["paths"]
    assert len(payload["paths"]) > 1


def test_openapi_export_stable(tmp_path: Path) -> None:
    """Two consecutive exports produce byte-identical files (sort_keys stability)."""
    export = _load_export_module()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert export.main([str(first)]) == 0
    assert export.main([str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()

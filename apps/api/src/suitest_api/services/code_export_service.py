"""Code export service — generates runnable test scripts from step.code (M2-12).

Supports three target frameworks:
  * ``playwright`` (default) — TypeScript Playwright test.
  * ``cypress`` — JavaScript Cypress spec.
  * ``selenium`` — Python Selenium test.

Steps with no ``code`` field are rendered as ``# TODO`` / ``// TODO`` comments
so partial test cases still export cleanly without a validation error.

API contract: docs/API.md §3.18. No LLM required.
"""

from __future__ import annotations

import json
import re
import uuid

from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.code_export import CodeExport

_VALID_TARGETS: frozenset[str] = frozenset({"playwright", "cypress", "selenium"})

_EXT: dict[str, str] = {
    "playwright": ".spec.ts",
    "cypress": ".cy.js",
    "selenium": ".py",
}


class UnsupportedTargetError(ValueError):
    """Raised when *target* is not a recognised framework name."""

    def __init__(self, target: str) -> None:
        super().__init__(f"unsupported export target: {target!r}")
        self.target = target


def generate_export(
    case: TestCase,
    steps: list[TestStep],
    target: str,
    *,
    user_id: uuid.UUID | None = None,
) -> CodeExport:
    """Build a :class:`CodeExport` ORM row (not yet added to a session).

    The caller is responsible for ``session.add(row)`` and
    ``await session.commit()`` so the row participates in the surrounding
    request transaction.

    Raises :class:`UnsupportedTargetError` for unknown *target* strings.
    """
    if target not in _VALID_TARGETS:
        raise UnsupportedTargetError(target)

    generators = {
        "playwright": _playwright,
        "cypress": _cypress,
        "selenium": _selenium,
    }
    code_text = generators[target](case, steps)

    return CodeExport(
        case_id=case.id,
        target=target,
        exported_code_text=code_text,
        user_id=user_id,
    )


def export_filename(case: TestCase, target: str) -> str:
    """Return the ``Content-Disposition`` filename for *target*."""
    ext = _EXT.get(target, ".txt")
    return f"{case.public_id}{ext}"


# ---------------------------------------------------------------------------
# Private generators
# ---------------------------------------------------------------------------


def _js_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "test"


def _playwright(case: TestCase, steps: list[TestStep]) -> str:
    dataset_rows = getattr(case, "dataset_rows", None)
    if isinstance(dataset_rows, str):
        try:
            dataset_rows = json.loads(dataset_rows)
        except Exception:
            dataset_rows = None
    lines: list[str] = [
        "import { test, expect } from '@playwright/test';",
        "",
    ]
    if dataset_rows and isinstance(dataset_rows, list) and len(dataset_rows) > 0:
        active_rows = [
            r for r in dataset_rows if r.get("__enabled", True) and r.get("enabled", True)
        ] or dataset_rows
        clean_rows = []
        for r in active_rows:
            raw_vals = (r.get("values") if isinstance(r.get("values"), dict) else r) or {}
            clean_rows.append({k: v for k, v in raw_vals.items() if not k.startswith("__")})
        lines.append(f"const dataset = {json.dumps(clean_rows, indent=2)};")
        lines.append("")
        lines.append("dataset.forEach((data, index) => {")
        escaped_title = _js_str(case.name)[1:-1]
        lines.append(f"  test(`{escaped_title} [row ${{index + 1}}]`, async ({{ page }}) => {{")
        for step in steps:
            lines.append(f"    // {step.action}")
            if step.expected:
                lines.append(f"    // Expected: {step.expected}")
            if step.code:
                for code_line in step.code.splitlines():
                    lines.append(f"    {code_line}")
            else:
                lines.append("    // TODO: no code defined for this step")
            lines.append("")
        lines.append("  });")
        lines.append("});")
    else:
        lines.append(f"test({_js_str(case.name)}, async ({{ page }}) => {{")
        for step in steps:
            lines.append(f"  // {step.action}")
            if step.expected:
                lines.append(f"  // Expected: {step.expected}")
            if step.code:
                for code_line in step.code.splitlines():
                    lines.append(f"  {code_line}")
            else:
                lines.append("  // TODO: no code defined for this step")
            lines.append("")
        lines.append("});")
    return "\n".join(lines) + "\n"


def _cypress(case: TestCase, steps: list[TestStep]) -> str:
    dataset_rows = getattr(case, "dataset_rows", None)
    if isinstance(dataset_rows, str):
        try:
            dataset_rows = json.loads(dataset_rows)
        except Exception:
            dataset_rows = None
    lines: list[str] = [
        f"describe({_js_str(case.name)}, () => {{",
    ]
    if dataset_rows and isinstance(dataset_rows, list) and len(dataset_rows) > 0:
        active_rows = [
            r for r in dataset_rows if r.get("__enabled", True) and r.get("enabled", True)
        ] or dataset_rows
        clean_rows = []
        for r in active_rows:
            raw_vals = (r.get("values") if isinstance(r.get("values"), dict) else r) or {}
            clean_rows.append({k: v for k, v in raw_vals.items() if not k.startswith("__")})
        lines.append(f"  const dataset = {json.dumps(clean_rows, indent=2)};")
        lines.append("")
        lines.append("  dataset.forEach((data, index) => {")
        lines.append("    it(`should execute all steps [row ${index + 1}]`, () => {")
        for step in steps:
            lines.append(f"      // {step.action}")
            if step.expected:
                lines.append(f"      // Expected: {step.expected}")
            if step.code:
                for code_line in step.code.splitlines():
                    lines.append(f"      {code_line}")
            else:
                lines.append("      // TODO: no code defined for this step")
            lines.append("")
        lines.append("    });")
        lines.append("  });")
    else:
        lines.append("  it('should execute all steps', () => {")
        for step in steps:
            lines.append(f"    // {step.action}")
            if step.expected:
                lines.append(f"    // Expected: {step.expected}")
            if step.code:
                for code_line in step.code.splitlines():
                    lines.append(f"    {code_line}")
            else:
                lines.append("    // TODO: no code defined for this step")
            lines.append("")
        lines.append("  });")
    lines.append("});")
    return "\n".join(lines) + "\n"


def _selenium(case: TestCase, steps: list[TestStep]) -> str:
    slug = _slugify(case.name)
    lines: list[str] = [
        "import pytest",
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "",
        "",
    ]
    dataset_rows = getattr(case, "dataset_rows", None)
    dataset_schema = getattr(case, "dataset_schema", None)
    if isinstance(dataset_rows, str):
        try:
            dataset_rows = json.loads(dataset_rows)
        except Exception:
            dataset_rows = None
    if isinstance(dataset_schema, str):
        try:
            dataset_schema = json.loads(dataset_schema)
        except Exception:
            dataset_schema = None
    if dataset_rows and isinstance(dataset_rows, list) and len(dataset_rows) > 0:
        active_rows = [
            r for r in dataset_rows if r.get("__enabled", True) and r.get("enabled", True)
        ] or dataset_rows
        keys = [
            k
            for k in (dataset_schema or list(dataset_rows[0].keys()))
            if not k.startswith("__") and k not in ("id", "name", "enabled")
        ]
        if keys:
            argnames = ", ".join(keys)
            param_values = []
            for r in active_rows:
                r_vals = (r.get("values") if isinstance(r.get("values"), dict) else r) or {}
                vals = [r_vals.get(k) for k in keys]
                param_values.append(tuple(vals) if len(keys) > 1 else vals[0])
            lines.append(f'@pytest.mark.parametrize("{argnames}", {param_values!r})')
            lines.append(f"def test_{slug}({argnames}):")
        else:
            lines.append(f"def test_{slug}():")
    else:
        lines.append(f"def test_{slug}():")
    lines.extend(
        [
            f'    """{case.name} ({case.public_id})"""',
            "    driver = webdriver.Chrome()",
            "    try:",
        ]
    )
    for step in steps:
        lines.append(f"        # {step.action}")
        if step.expected:
            lines.append(f"        # Expected: {step.expected}")
        if step.code:
            for code_line in step.code.splitlines():
                lines.append(f"        {code_line}")
        else:
            lines.append("        # TODO: no code defined for this step")
        lines.append("")
    lines.append("    finally:")
    lines.append("        driver.quit()")
    return "\n".join(lines) + "\n"

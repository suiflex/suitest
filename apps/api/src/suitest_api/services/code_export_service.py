"""Code export service — generates runnable test scripts from step.code (M2-12).

Supports three target frameworks:
  * ``playwright`` (default) — TypeScript Playwright test.
  * ``cypress`` — JavaScript Cypress spec.
  * ``selenium`` — Python Selenium test.

Steps with no ``code`` field are rendered as ``# TODO`` / ``// TODO`` comments
so partial test cases still export cleanly without a validation error.

API contract: docs/API.md §3.18. Always ZERO-tier-safe — no LLM required.
"""

from __future__ import annotations

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
    lines: list[str] = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test({_js_str(case.name)}, async ({{ page }}) => {{",
    ]
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
    lines: list[str] = [
        f"describe({_js_str(case.name)}, () => {{",
        "  it('should execute all steps', () => {",
    ]
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
        f"def test_{slug}():",
        f'    """{case.name} ({case.public_id})"""',
        "    driver = webdriver.Chrome()",
        "    try:",
    ]
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

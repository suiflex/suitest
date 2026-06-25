"""Unit tests for code_export_service — no DB required.

These tests exercise the code-generation logic directly, without any HTTP or
ORM machinery.  All inputs are plain in-memory ORM instances (no session, no
commit).  Covers all three frameworks, TODO rendering for codeless steps, the
``UnsupportedTargetError`` path, and ``export_filename``.
"""

from __future__ import annotations

import uuid

import pytest
from suitest_api.services.code_export_service import (
    UnsupportedTargetError,
    export_filename,
    generate_export,
)
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.code_export import CodeExport
from suitest_shared.domain.enums import CaseSource, TargetKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _case(name: str = "Login flow", public_id: str = "TC-1") -> TestCase:
    return TestCase(
        id="case_001",
        suite_id="suite_001",
        public_id=public_id,
        name=name,
        source=CaseSource.MANUAL,
    )


def _step(
    order: int,
    action: str,
    expected: str = "ok",
    code: str | None = None,
) -> TestStep:
    return TestStep(
        id=f"step_{order:03d}",
        case_id="case_001",
        order=order,
        action=action,
        expected=expected,
        code=code,
        mcp_provider="playwright-mcp",
        target_kind=TargetKind.FE_WEB,
    )


# ---------------------------------------------------------------------------
# generate_export — playwright
# ---------------------------------------------------------------------------


def test_playwright_scaffold() -> None:
    case = _case()
    steps = [
        _step(0, "Open /login", code="await page.goto('/login');"),
        _step(1, "Click submit", code="await page.click('#submit');"),
    ]
    row = generate_export(case, steps, "playwright")
    assert isinstance(row, CodeExport)
    assert row.case_id == "case_001"
    assert row.target == "playwright"
    text = row.exported_code_text
    assert "import { test, expect } from '@playwright/test';" in text
    assert "Login flow" in text
    assert "await page.goto('/login');" in text
    assert "await page.click('#submit');" in text
    assert "// Open /login" in text


def test_playwright_multiline_code() -> None:
    case = _case()
    steps = [_step(0, "Fill form", code="await page.fill('#u', 'a');\nawait page.fill('#p', 'b');")]
    row = generate_export(case, steps, "playwright")
    assert "await page.fill('#u', 'a');" in row.exported_code_text
    assert "await page.fill('#p', 'b');" in row.exported_code_text


def test_playwright_no_code_step_renders_todo() -> None:
    case = _case()
    steps = [_step(0, "Unimplemented step", code=None)]
    row = generate_export(case, steps, "playwright")
    assert "TODO: no code defined for this step" in row.exported_code_text


def test_playwright_expected_rendered_as_comment() -> None:
    case = _case()
    steps = [_step(0, "Do X", expected="Y should happen", code="await page.click('#x');")]
    row = generate_export(case, steps, "playwright")
    assert "// Expected: Y should happen" in row.exported_code_text


# ---------------------------------------------------------------------------
# generate_export — cypress
# ---------------------------------------------------------------------------


def test_cypress_scaffold() -> None:
    case = _case()
    steps = [_step(0, "Navigate", code="cy.visit('/login');")]
    row = generate_export(case, steps, "cypress")
    text = row.exported_code_text
    assert "describe(" in text
    assert "Login flow" in text
    assert "it(" in text
    assert "cy.visit('/login');" in text
    assert row.target == "cypress"


def test_cypress_no_code_step_renders_todo() -> None:
    case = _case()
    steps = [_step(0, "Placeholder", code=None)]
    row = generate_export(case, steps, "cypress")
    assert "TODO: no code defined for this step" in row.exported_code_text


# ---------------------------------------------------------------------------
# generate_export — selenium
# ---------------------------------------------------------------------------


def test_selenium_scaffold() -> None:
    case = _case()
    steps = [_step(0, "Navigate to login", code="driver.get('/login')")]
    row = generate_export(case, steps, "selenium")
    text = row.exported_code_text
    assert "def test_" in text
    assert "webdriver.Chrome()" in text
    assert "driver.quit()" in text
    assert "driver.get('/login')" in text
    assert row.target == "selenium"


def test_selenium_name_slugified() -> None:
    case = _case(name="Login & Register Flow!")
    steps = [_step(0, "Do it", code="pass")]
    row = generate_export(case, steps, "selenium")
    assert "def test_login_register_flow" in row.exported_code_text


def test_selenium_no_code_step_renders_todo() -> None:
    case = _case()
    steps = [_step(0, "Unimplemented", code=None)]
    row = generate_export(case, steps, "selenium")
    assert "TODO: no code defined for this step" in row.exported_code_text


# ---------------------------------------------------------------------------
# generate_export — user_id propagation
# ---------------------------------------------------------------------------


def test_generate_export_stores_user_id() -> None:
    uid = uuid.uuid4()
    case = _case()
    steps = [_step(0, "A", code="x")]
    row = generate_export(case, steps, "playwright", user_id=uid)
    assert row.user_id == uid


def test_generate_export_null_user_id_by_default() -> None:
    case = _case()
    steps = [_step(0, "A", code="x")]
    row = generate_export(case, steps, "playwright")
    assert row.user_id is None


# ---------------------------------------------------------------------------
# generate_export — unsupported target
# ---------------------------------------------------------------------------


def test_unsupported_target_raises() -> None:
    case = _case()
    steps = [_step(0, "A", code="x")]
    with pytest.raises(UnsupportedTargetError) as exc_info:
        generate_export(case, steps, "jest")
    assert exc_info.value.target == "jest"


# ---------------------------------------------------------------------------
# export_filename
# ---------------------------------------------------------------------------


def test_export_filename_playwright() -> None:
    case = _case(public_id="TC-99")
    assert export_filename(case, "playwright") == "TC-99.spec.ts"


def test_export_filename_cypress() -> None:
    case = _case(public_id="TC-100")
    assert export_filename(case, "cypress") == "TC-100.cy.js"


def test_export_filename_selenium() -> None:
    case = _case(public_id="TC-101")
    assert export_filename(case, "selenium") == "TC-101.py"


def test_export_filename_unknown_falls_back_to_txt() -> None:
    case = _case(public_id="TC-102")
    assert export_filename(case, "unknown") == "TC-102.txt"

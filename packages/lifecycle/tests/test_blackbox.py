"""Hermetic unit tests for the blackbox DOM engine (no browser, no network).

The acceptance-critical property under test: NOTHING requires a data-testid.
Fixtures below describe a login form and pages the way a generic React/Vue/
Angular app renders them — labels, placeholders, names, button text only.
"""

from __future__ import annotations

import json
import py_compile
from pathlib import Path

from suitest_lifecycle.blackbox.detector import (
    detect_login_form,
    detect_page_pattern,
    is_destructive,
)
from suitest_lifecycle.blackbox.generator import export_blackbox_tests, generate_cases
from suitest_lifecycle.blackbox.graph import build_graph
from suitest_lifecycle.blackbox.models import (
    BlackboxUiConfig,
    DiscoveryResult,
    ElementInfo,
    LoginProbe,
    PageInfo,
)
from suitest_lifecycle.blackbox.selector import build_locator
from suitest_lifecycle.models import Mode
from suitest_lifecycle.paths import build_paths


def _el(**kw: object) -> ElementInfo:
    return ElementInfo(**kw)  # type: ignore[arg-type]


# --- selector strategy -------------------------------------------------------


def test_selector_prefers_testid_then_degrades_gracefully() -> None:
    e = _el(tag="input", testid="login-email-input", testid_attr="data-testid", label="Email")
    assert build_locator(e) == 'page.get_by_test_id("login-email-input")'
    # same element, app without testids → label tier
    e2 = _el(tag="input", label="Email")
    assert build_locator(e2) == 'page.get_by_label("Email").first'
    e3 = _el(tag="input", placeholder="you@example.com")
    assert "get_by_placeholder" in build_locator(e3)
    e4 = _el(tag="input", name="email")
    assert build_locator(e4) == "page.locator('input[name=\"email\"]').first"
    e5 = _el(tag="button", text="Sign in")
    assert build_locator(e5) == 'page.get_by_role("button", name="Sign in").first'
    e6 = _el(tag="input", css="form > input:nth-of-type(2)")
    assert "form > input:nth-of-type(2)" in build_locator(e6)


def test_selector_ignore_testids_flag_skips_tier_one() -> None:
    e = _el(tag="input", testid="login-email-input", testid_attr="data-testid", label="Email")
    assert build_locator(e, ignore_testids=True) == 'page.get_by_label("Email").first'


# --- login detection (NO testids anywhere) ------------------------------------


def _login_page_no_testids() -> PageInfo:
    return PageInfo(
        route="/login",
        inputs=[
            _el(tag="input", kind="input", input_type="text", name="username", label="Username"),
            _el(tag="input", kind="input", input_type="password", name="pass", label="Password"),
            _el(tag="input", kind="checkbox", input_type="checkbox", label="Remember me"),
        ],
        buttons=[_el(tag="button", kind="button", text="Log in")],
        visible_text_sample="Welcome back. Please log in.",
    )


def test_detect_login_form_without_any_testid() -> None:
    form = detect_login_form(_login_page_no_testids())
    assert form.found()
    assert "username" in form.username.lower() or "Username" in form.username
    assert "password" in form.password.lower() or "Password" in form.password
    assert "Log in" in form.submit
    assert form.remember  # remember-me checkbox picked up


def test_detect_login_form_absent_when_no_password_field() -> None:
    page = PageInfo(route="/", inputs=[_el(tag="input", input_type="text", name="q")])
    assert not detect_login_form(page).found()


# --- page patterns -------------------------------------------------------------


def test_page_pattern_classification() -> None:
    assert detect_page_pattern(_login_page_no_testids()) == "login"
    assert (
        detect_page_pattern(
            PageInfo(route="/items", has_table=True, visible_text_sample="Items list")
        )
        == "list"
    )
    assert (
        detect_page_pattern(
            PageInfo(
                route="/items/new",
                inputs=[
                    _el(tag="input", input_type="text", name="name"),
                    _el(tag="input", input_type="number", name="price"),
                ],
                buttons=[_el(tag="button", text="Save")],
                visible_text_sample="Create item",
            )
        )
        == "form"
    )
    assert (
        detect_page_pattern(PageInfo(route="/missing", visible_text_sample="404 — Not Found"))
        == "not_found"
    )
    assert detect_page_pattern(PageInfo(route="/x", blank=True)) == "blank"
    assert (
        detect_page_pattern(PageInfo(route="/x", visible_text_sample="403 Forbidden"))
        == "forbidden"
    )


def test_destructive_detection_guards_safe_mode() -> None:
    assert is_destructive(_el(tag="button", text="Delete product"))
    assert is_destructive(_el(tag="a", text="Log out"))
    assert is_destructive(_el(tag="button", text="Cancel subscription"))
    assert not is_destructive(_el(tag="button", text="Save"))


# --- generation ------------------------------------------------------------------


def _discovery_no_testids() -> DiscoveryResult:
    login = _login_page_no_testids()
    home = PageInfo(
        route="/home",
        pattern="dashboard",
        visible_text_sample="Dashboard overview",
        nav_routes=["/items"],
    )
    items = PageInfo(
        route="/items",
        pattern="list",
        has_table=True,
        row_locator="page.locator('table tbody tr')",
        search_locator='page.get_by_placeholder("Search").first',
        visible_text_sample="Items",
    )
    form_page = PageInfo(
        route="/items/new",
        pattern="form",
        has_form=True,
        inputs=[
            _el(tag="input", input_type="text", name="name", required=True),
            _el(tag="input", input_type="number", name="price", required=True),
        ],
        buttons=[_el(tag="button", text="Save", input_type="submit")],
        visible_text_sample="Create item",
    )
    d = DiscoveryResult(base_url="http://app.local")
    d.login = detect_login_form(login)
    d.login.route = "/login"
    d.login_probe = LoginProbe(attempted=True, success=True, landed_route="/home")
    d.pages = [login, home, items, form_page]
    return d


def test_generate_cases_covers_core_suite_without_testids(tmp_path: Path) -> None:
    cfg = BlackboxUiConfig(target_url="http://app.local")
    cfg.auth.username = "qa@example.com"
    cfg.auth.password = "secret"
    pairs = generate_cases(_discovery_no_testids(), cfg)
    titles = [c.title for c, _ in pairs]
    assert "app_loads_successfully" in titles
    assert "no_critical_console_errors_on_load" in titles
    assert "login_with_valid_credentials_succeeds" in titles
    assert "login_with_invalid_credentials_fails" in titles
    assert "main_navigation_does_not_crash" in titles
    assert any(t.startswith("list_page_") for t in titles)
    assert any(t.startswith("search_on_") for t in titles)
    assert any(t.startswith("form_on_") for t in titles)
    # no generated body may reference the old suitest-example convention
    for _, body in pairs:
        assert "login-email-input" not in body
        assert "dashboard-page" not in body


def test_exported_files_compile(tmp_path: Path) -> None:
    cfg = BlackboxUiConfig(target_url="http://app.local")
    cfg.auth.username = "qa@example.com"
    cfg.auth.password = "secret"
    paths = build_paths(tmp_path, Mode.FRONTEND)
    cases = export_blackbox_tests(_discovery_no_testids(), cfg, paths)
    assert len(cases) >= 8
    for case in cases:
        py_compile.compile(str(paths.test_file(str(case.automation_file))), doraise=True)


# --- graph + serialization ----------------------------------------------------------


def test_graph_is_json_serializable_with_expected_nodes() -> None:
    graph = build_graph(_discovery_no_testids())
    blob = json.dumps(graph)
    assert '"kind": "page"' in blob
    assert '"kind": "form"' in blob
    assert '"kind": "table"' in blob
    kinds = {e["kind"] for e in graph["edges"]}
    assert {"navigation", "submit", "validation"} <= kinds


def test_discovery_round_trips_through_json() -> None:
    d = _discovery_no_testids()
    restored = DiscoveryResult.from_json(json.loads(json.dumps(d.to_json())))
    assert [p.route for p in restored.pages] == [p.route for p in d.pages]
    assert restored.login is not None and restored.login.found()
    assert restored.login_probe.success


# --- PRD upload flow (markdown ingest + LLM plan merge) --------------------------


def test_prd_markdown_ingest() -> None:
    from suitest_lifecycle.blackbox.prd_ingest import parse_prd_markdown

    doc = parse_prd_markdown(
        "# Inventory App\n\n"
        "## Authentication\n"
        "Users sign in with email + password.\n"
        "- Valid login lands on the dashboard\n"
        "- Invalid login shows an error\n\n"
        "## Products\n"
        "- Products list shows name, SKU, price\n"
        "- Search filters by name or SKU\n"
    )
    assert doc.title == "Inventory App"
    assert [s.heading for s in doc.sections] == ["Authentication", "Products"]
    assert len(doc.requirements) == 4
    ctx = doc.as_prompt_context()
    assert "Invalid login shows an error" in ctx


def test_prd_requires_markdown(tmp_path: Path) -> None:
    import pytest
    from suitest_lifecycle.blackbox.prd_ingest import load_prd

    bad = tmp_path / "spec.pdf"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="markdown"):
        load_prd(bad)


class _FakePrdLlm:
    """Planner proposes one PRD case; codegen succeeds for it."""

    def plan_from_prd(self, prd_context, app_context, existing_titles, *, allow_mutation=False):
        assert "Invalid login shows an error" in prd_context
        return [
            {
                "title": "prd_invalid_login_shows_error",
                "description": "PRD: invalid login shows an error",
                "category": "Auth",
                "priority": "High",
                "route": "/login",
                "steps": [["action", "submit wrong password"], ["assertion", "error visible"]],
            },
            {
                "title": "prd_unknown_route_case",
                "description": "route not discovered → falls back to /",
                "category": "PRD",
                "priority": "Low",
                "route": "/does-not-exist",
                "steps": [["assertion", "renders"]],
            },
        ]

    def generate_frontend_body(self, case, dom_context):
        if case.title == "prd_invalid_login_shows_error":
            return (
                "async def _body(page):\n"
                '    _begin("action", "open login")\n'
                '    await page.goto(f"{BASE_URL}/login")\n'
                "    await _ok(page)\n"
                '    _begin("assertion", "error region check")\n'
                '    await expect(page.locator("body")).to_be_visible(timeout=TIMEOUT)\n'
                "    await _ok(page)\n"
            )
        return None  # second case → deterministic fallback probe


def test_prd_cases_merge_with_baseline(tmp_path: Path) -> None:
    from suitest_lifecycle.blackbox.prd_ingest import parse_prd_markdown

    cfg = BlackboxUiConfig(target_url="http://app.local")
    cfg.auth.username = "qa@example.com"
    cfg.auth.password = "secret"
    prd = parse_prd_markdown("# App\n## Auth\n- Invalid login shows an error\n")
    paths = build_paths(tmp_path, Mode.FRONTEND)
    cases = export_blackbox_tests(
        _discovery_no_testids(), cfg, paths, llm=_FakePrdLlm(), prd_context=prd.as_prompt_context()
    )
    titles = [c.title for c in cases]
    assert "prd_invalid_login_shows_error" in titles  # LLM body accepted
    assert "prd_unknown_route_case" in titles  # fallback probe kept the case alive
    assert titles.index("app_loads_successfully") < titles.index("prd_invalid_login_shows_error")
    prd_case = next(c for c in cases if c.title == "prd_invalid_login_shows_error")
    assert prd_case.source_ref == "bb:prd /login"
    for case in cases:
        py_compile.compile(str(paths.test_file(str(case.automation_file))), doraise=True)

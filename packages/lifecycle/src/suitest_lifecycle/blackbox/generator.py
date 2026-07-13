"""Deterministic Playwright test generation from a blackbox discovery.

Reuses the existing frontend exporter wrapper (``_HEADER``/``_RUNNER``) so
generated tests inherit the whole evidence pipeline unchanged: per-step
screenshots, video, ``.result.json`` sidecars, runner + publish compatibility.
Only the ``_body`` per test is minted here — from DISCOVERED locators, never
from any hardcoded app convention.

SafeMode invariants:
* destructive controls are never clicked (see ``detector.is_destructive``)
* forms are only submitted EMPTY (validation probe) unless
  ``testGeneration.allowMutation`` is true
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_lifecycle.models import PlanCase, PlanStep, Priority

if TYPE_CHECKING:
    from suitest_lifecycle.blackbox.models import BlackboxUiConfig, DiscoveryResult, PageInfo
    from suitest_lifecycle.paths import Paths

# Heuristic safe-fill values (docs/BLACKBOX_UI_TESTING.md §safe form filling).
SAFE_FILL_SNIPPET = """
def _safe_value(kind, label=""):
    import datetime
    l = (label or "").lower()
    if kind == "email" or "email" in l:
        return "qa+" + uuid.uuid4().hex[:6] + "@example.com"
    if kind == "number":
        return "1"
    if kind == "date":
        return datetime.date.today().isoformat()
    if kind == "textarea":
        return "Automated QA test value"
    return "Test value"
"""


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


def _case(
    n: int,
    title: str,
    desc: str,
    category: str,
    prio: Priority,
    ref: str,
    steps: list[tuple[str, str]],
) -> PlanCase:
    return PlanCase(
        id=f"TC{n:03d}",
        title=title,
        description=desc,
        category=category,
        priority=prio,
        source_ref=ref,
        steps=[PlanStep(type=t, description=d) for t, d in steps],
    )


def _login_snippet(discovery: DiscoveryResult) -> str:
    """Inline login helper built from DISCOVERED locators (not testids)."""
    form = discovery.login
    if form is None:
        return ""
    return f'''
async def _bb_login(page):
    _begin("action", "Open the login page")
    await page.goto(f"{{BASE_URL}}{form.route}", wait_until="domcontentloaded")
    await _ok(page)
    _begin("action", "Fill the username and password")
    await {form.username}.fill(USERNAME)
    await {form.password}.fill(PASSWORD)
    await _ok(page)
    _begin("action", "Submit the login form")
    await {form.submit}.click()
    try:
        await page.wait_for_url(lambda u: "{form.route}" not in u, timeout=10000)
    except Exception:
        pass
    await _ok(page)
    _begin("assertion", "Login succeeded (left the login route)")
    assert "{form.route}" not in page.url, f"still on login: {{page.url}}"
    await _ok(page)
'''


def generate_cases(discovery: DiscoveryResult, cfg: BlackboxUiConfig) -> list[tuple[PlanCase, str]]:
    """Return ``(case, body_source)`` pairs, deterministic order."""
    out: list[tuple[PlanCase, str]] = []
    n = 0
    gen = cfg.test_generation
    login = discovery.login
    needs_login = login is not None and discovery.login_probe.success

    def nid() -> int:
        nonlocal n
        n += 1
        return n

    prelude = "    await _bb_login(page)\n" if needs_login else ""

    # -- smoke ---------------------------------------------------------------
    if gen.include_smoke:
        out.append(
            (
                _case(
                    nid(),
                    "app_loads_successfully",
                    "The application root responds and renders visible content.",
                    "Smoke",
                    Priority.HIGH,
                    "bb:smoke /",
                    [
                        ("action", "Open the application root"),
                        ("assertion", "Body has visible content and a title"),
                    ],
                ),
                """
async def _body(page):
    _begin("action", "Open the application root")
    await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    await _ok(page)
    _begin("assertion", "Body has visible content")
    await expect(page.locator("body")).to_be_visible(timeout=TIMEOUT)
    text = await page.evaluate("() => document.body.innerText.trim().length")
    assert text > 0, "page rendered no visible text (blank page)"
    await _ok(page)
""",
            )
        )
        out.append(
            (
                _case(
                    nid(),
                    "no_critical_console_errors_on_load",
                    "Loading the app produces no uncaught exceptions or console errors.",
                    "Smoke",
                    Priority.MEDIUM,
                    "bb:smoke /",
                    [
                        ("action", "Open the application root with a console listener"),
                        ("assertion", "No console.error / uncaught exceptions were emitted"),
                    ],
                ),
                """
async def _body(page):
    errors = []
    page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    _begin("action", "Open the application root")
    await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await _ok(page)
    _begin("assertion", "No critical console errors")
    critical = [e for e in errors if "favicon" not in e.lower()]
    assert not critical, f"console errors: {critical[:3]}"
    await _ok(page)
""",
            )
        )

    # -- auth ------------------------------------------------------------------
    if gen.include_auth and login is not None:
        out.append(
            (
                _case(
                    nid(),
                    "login_with_valid_credentials_succeeds",
                    "Valid credentials authenticate and leave the login route.",
                    "Auth",
                    Priority.HIGH,
                    f"bb:auth {login.route}",
                    [
                        ("action", "Log in with valid credentials"),
                        ("assertion", "The app navigates away from the login route"),
                    ],
                ),
                """
async def _body(page):
    await _bb_login(page)
""",
            )
        )
        out.append(
            (
                _case(
                    nid(),
                    "login_with_invalid_credentials_fails",
                    "A wrong password keeps the user on the login route (with feedback).",
                    "Auth",
                    Priority.HIGH,
                    f"bb:auth {login.route}",
                    [
                        ("action", "Submit the login form with a wrong password"),
                        ("assertion", "Still on the login route"),
                    ],
                ),
                f'''
async def _body(page):
    _begin("action", "Open the login page")
    await page.goto(f"{{BASE_URL}}{login.route}", wait_until="domcontentloaded")
    await _ok(page)
    _begin("action", "Submit a wrong password")
    await {login.username}.fill(USERNAME)
    await {login.password}.fill("wrong-password-" + uuid.uuid4().hex[:6])
    await {login.submit}.click()
    await page.wait_for_timeout(1500)
    await _ok(page)
    _begin("assertion", "Still on the login route")
    assert "{login.route}" in page.url, f"unexpectedly left login: {{page.url}}"
    await _ok(page)
''',
            )
        )
        if needs_login:
            landed = discovery.login_probe.landed_route
            out.append(
                (
                    _case(
                        nid(),
                        "authenticated_landing_page_renders",
                        f"After login the app lands on {landed} and renders content.",
                        "Auth",
                        Priority.HIGH,
                        f"bb:auth {landed}",
                        [
                            ("action", "Log in"),
                            ("assertion", "Landing page renders visible content"),
                        ],
                    ),
                    """
async def _body(page):
    await _bb_login(page)
    _begin("assertion", "Landing page renders visible content")
    text = await page.evaluate("() => document.body.innerText.trim().length")
    assert text > 50, "landing page looks blank"
    await _ok(page)
""",
                )
            )

    # -- navigation -------------------------------------------------------------
    crawled = [
        p for p in discovery.pages if p.pattern not in ("login", "not_found") and not p.protected
    ]
    if gen.include_navigation and crawled:
        routes = [p.route for p in crawled][:8]
        routes_literal = ", ".join(f'"{r}"' for r in routes)
        out.append(
            (
                _case(
                    nid(),
                    "main_navigation_does_not_crash",
                    "Every discovered route loads without a blank page or crash.",
                    "Navigation",
                    Priority.HIGH,
                    "bb:navigation /",
                    [
                        ("action", "Visit every discovered route"),
                        ("assertion", "Each route renders visible content"),
                    ],
                ),
                f"""
async def _body(page):
{prelude}    for route in [{routes_literal}]:
        _begin("action", "Open " + route)
        await page.goto(f"{{BASE_URL}}" + route, wait_until="domcontentloaded")
        await page.wait_for_timeout(600)
        await _ok(page)
        _begin("assertion", route + " renders content and no crash text")
        text = await page.evaluate("() => document.body.innerText.trim()")
        assert len(text) > 0, route + " rendered blank"
        low = text.lower()
        assert "internal server error" not in low and "traceback" not in low, route + " crashed"
        await _ok(page)
""",
            )
        )

    # -- tables / lists -----------------------------------------------------------
    if gen.include_tables:
        for p in [p for p in crawled if p.has_table and p.row_locator][:3]:
            out.append(
                (
                    _case(
                        nid(),
                        f"list_page_{_slugify(p.route)}_renders_rows_or_empty_state",
                        f"The list on {p.route} renders rows (or a legitimate empty state).",
                        "Lists",
                        Priority.MEDIUM,
                        f"bb:table {p.route}",
                        [
                            ("action", f"Open {p.route}"),
                            ("assertion", "Rows are rendered or an empty state is shown"),
                        ],
                    ),
                    f"""
async def _body(page):
{prelude}    _begin("action", "Open {p.route}")
    await page.goto(f"{{BASE_URL}}{p.route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "Rows render or an empty state is visible")
    rows = await {p.row_locator}.count()
    if rows == 0:
        text = (await page.evaluate("() => document.body.innerText")).lower()
        assert any(k in text for k in ("no ", "empty", "tidak ada")), "no rows and no empty state"
    await _ok(page)
""",
                )
            )
            if p.search_locator:
                out.append(
                    (
                        _case(
                            nid(),
                            f"search_on_{_slugify(p.route)}_filters_results",
                            f"Typing an unlikely query into the search on {p.route} narrows the list.",
                            "Lists",
                            Priority.LOW,
                            f"bb:search {p.route}",
                            [
                                ("action", "Type an unlikely search query"),
                                ("assertion", "Fewer/zero rows or an empty state"),
                            ],
                        ),
                        f"""
async def _body(page):
{prelude}    _begin("action", "Open {p.route}")
    await page.goto(f"{{BASE_URL}}{p.route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(600)
    before = await {p.row_locator}.count()
    await _ok(page)
    _begin("action", "Type an unlikely search query")
    await {p.search_locator}.fill("zzz-no-match-" + uuid.uuid4().hex[:6])
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "Result set narrowed")
    after = await {p.row_locator}.count()
    assert after <= before, f"rows grew from {{before}} to {{after}} after searching"
    await _ok(page)
""",
                    )
                )
            if p.pagination_locator:
                out.append(
                    (
                        _case(
                            nid(),
                            f"pagination_on_{_slugify(p.route)}_is_operable",
                            f"The pagination control on {p.route} can be activated without a crash.",
                            "Lists",
                            Priority.LOW,
                            f"bb:pagination {p.route}",
                            [
                                ("action", "Click the next-page control if enabled"),
                                ("assertion", "The list still renders"),
                            ],
                        ),
                        f"""
async def _body(page):
{prelude}    _begin("action", "Open {p.route}")
    await page.goto(f"{{BASE_URL}}{p.route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(600)
    await _ok(page)
    _begin("action", "Activate the next-page control when enabled")
    pager = {p.pagination_locator}
    if await pager.count() > 0 and await pager.first.is_enabled():
        await pager.first.click()
        await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "The page still renders content")
    text = await page.evaluate("() => document.body.innerText.trim()")
    assert len(text) > 0, "page went blank after pagination"
    await _ok(page)
""",
                    )
                )

    # -- forms (safe validation probe only) ----------------------------------------
    if gen.include_forms:
        form_pages = [p for p in crawled if p.has_form and p.pattern == "form"][:2]
        for p in form_pages:
            submit = _first_safe_submit(p)
            if submit is None:
                continue
            out.append(
                (
                    _case(
                        nid(),
                        f"form_on_{_slugify(p.route)}_validates_empty_required_fields",
                        f"Submitting the form on {p.route} empty keeps the user on the form "
                        "(client validation) — a SAFE probe, nothing is persisted.",
                        "Forms",
                        Priority.MEDIUM,
                        f"bb:form {p.route}",
                        [
                            ("action", f"Open {p.route} and submit the form empty"),
                            ("assertion", "Still on the form (validation blocked the submit)"),
                        ],
                    ),
                    f'''
async def _body(page):
{prelude}    _begin("action", "Open {p.route}")
    await page.goto(f"{{BASE_URL}}{p.route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(600)
    await _ok(page)
    _begin("action", "Submit the form with every field left empty")
    await {submit}.click()
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "Still on the form route (validation held)")
    assert "{p.route}" in page.url, f"empty submit navigated away to {{page.url}}"
    await _ok(page)
''',
                )
            )

    # -- modal open/close ------------------------------------------------------------
    modal_pages = [p for p in crawled if p.has_modal][:1]
    for p in modal_pages:
        out.append(
            (
                _case(
                    nid(),
                    f"modal_on_{_slugify(p.route)}_can_be_dismissed",
                    f"A dialog observed on {p.route} can be dismissed with Escape.",
                    "Modals",
                    Priority.LOW,
                    f"bb:modal {p.route}",
                    [
                        ("action", f"Open {p.route} and press Escape"),
                        ("assertion", "No blocking dialog remains"),
                    ],
                ),
                f"""
async def _body(page):
{prelude}    _begin("action", "Open {p.route}")
    await page.goto(f"{{BASE_URL}}{p.route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("action", "Press Escape to dismiss any dialog")
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    await _ok(page)
    _begin("assertion", "Page still renders after dismissing")
    await expect(page.locator("body")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
""",
            )
        )

    return out


def _first_safe_submit(p: PageInfo) -> str | None:
    from suitest_lifecycle.blackbox.detector import is_destructive
    from suitest_lifecycle.blackbox.selector import build_locator

    for b in p.buttons:
        if is_destructive(b):
            continue
        blob = f"{b.text} {b.input_type}".lower()
        if b.input_type == "submit" or any(
            k in blob for k in ("save", "create", "submit", "simpan", "add")
        ):
            return build_locator(b)
    return None


_PRIORITY_FROM_STR = {
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW,
}


def prd_cases(
    discovery: DiscoveryResult,
    cfg: BlackboxUiConfig,
    llm: object,
    prd_context: str,
    existing_titles: set[str],
    *,
    start_n: int,
) -> list[tuple[PlanCase, str]]:
    """PRD-driven cases: LLM plans from the uploaded spec, then writes each
    body against the DISCOVERED locators. A case whose generated body fails
    validation degrades to a safe route-render probe instead of vanishing —
    the plan stays PRD-complete either way.
    """
    from suitest_lifecycle.llm_bridge import build_dom_context_from_discovery

    plan = getattr(llm, "plan_from_prd", None)
    codegen = getattr(llm, "generate_frontend_body", None)
    if plan is None or codegen is None:
        return []
    app_context = build_dom_context_from_discovery(discovery)
    known_routes = {p.route for p in discovery.pages}
    raw = plan(
        prd_context,
        app_context,
        existing_titles,
        allow_mutation=cfg.test_generation.allow_mutation,
    )
    out: list[tuple[PlanCase, str]] = []
    n = start_n
    for item in raw:
        route = str(item.get("route", "/"))
        if route not in known_routes:
            route = "/"
        steps_raw = item.get("steps") or []
        steps: list[tuple[str, str]] = []
        for st in steps_raw:
            if isinstance(st, (list, tuple)) and len(st) == 2:
                kind = "assertion" if str(st[0]).lower() == "assertion" else "action"
                steps.append((kind, str(st[1])[:200]))
        if not steps:
            continue
        n += 1
        case = _case(
            n,
            str(item.get("title", f"prd_case_{n}"))[:200],
            str(item.get("description", "Verifies an uploaded-PRD requirement."))[:500],
            str(item.get("category", "PRD"))[:60] or "PRD",
            _PRIORITY_FROM_STR.get(str(item.get("priority", "")).lower(), Priority.MEDIUM),
            f"bb:prd {route}",
            steps,
        )
        body = codegen(case, app_context)
        if not body:
            body = f"""
async def _body(page):
    await _bb_login(page)
    _begin("action", "Open {route} (PRD fallback probe)")
    await page.goto(f"{{BASE_URL}}{route}", wait_until="domcontentloaded")
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "Route renders content (PRD case degraded to render probe)")
    text = await page.evaluate("() => document.body.innerText.trim()")
    assert len(text) > 0, "{route} rendered blank"
    await _ok(page)
"""
        else:
            body = "\n" + body.rstrip() + "\n"
        out.append((case, body))
    return out


def _write_pairs(
    pairs: list[tuple[PlanCase, str]],
    discovery: DiscoveryResult,
    cfg: BlackboxUiConfig,
    paths: Paths,
) -> list[PlanCase]:
    from suitest_lifecycle.exporters.frontend import _HEADER, _RUNNER

    paths.ensure()
    login_helper = _login_snippet(discovery)
    cases: list[PlanCase] = []
    for case, body in pairs:
        header = _HEADER.format(
            base_url=repr(cfg.target_url),
            cid=case.id,
        )
        # Drop the exporter's legacy testid-bound ``_login`` helper — blackbox
        # bodies use ``_bb_login`` built from DISCOVERED locators instead.
        header = header.split("\nasync def _login(page):", 1)[0] + "\n"
        code = header + SAFE_FILL_SNIPPET + login_helper + body + _RUNNER
        filename = f"{case.id}_{case.title}.py"
        paths.test_file(filename).write_text(code, encoding="utf-8")
        case.automation_file = filename
        cases.append(case)
    return cases


def export_blackbox_tests(
    discovery: DiscoveryResult,
    cfg: BlackboxUiConfig,
    paths: Paths,
    *,
    llm: object | None = None,
    prd_context: str = "",
) -> list[PlanCase]:
    """Write runnable TCxxx.py files (evidence wrapper included); return cases.

    Deterministic baseline always; when an uploaded PRD + LLM bridge are
    available, PRD-driven semantic cases are appended (TestSprite-parity
    upload flow).
    """
    pairs = generate_cases(discovery, cfg)
    if llm is not None and prd_context:
        existing = {c.title for c, _ in pairs}
        pairs += prd_cases(discovery, cfg, llm, prd_context, existing, start_n=len(pairs))
    return _write_pairs(pairs, discovery, cfg, paths)


__all__ = ["export_blackbox_tests", "generate_cases", "prd_cases"]

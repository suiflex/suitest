"""Unit tests for the heuristic URL crawler (M2 Task 3) — no DB, no browser.

Drive :class:`UrlCrawler` against a FAKE :class:`McpInvoker` that returns canned
responses for ``browser.navigate`` / ``browser.evaluate`` over a small synthetic
3-page site graph. Covers: a smoke case per visited page, form cases gated by
``include_form_cases``, ``max_depth`` / ``max_pages`` caps, the same-origin
filter, that every emitted step routes through ``playwright-mcp``, and the Faker
field-type mapping.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

import pytest
from suitest_agent.generators.url_crawler import UrlCrawler
from suitest_mcp.models import McpToolResult
from suitest_shared.schemas.generator_input import (
    CrawlerAuthConfig,
    CrawlerOptions,
    TestCaseDraft,
)

if TYPE_CHECKING:
    from suitest_mcp.invoker import InvokeContext, McpInvoker

# --- Synthetic 3-page same-origin site (+ one external link). ---------------

_ORIGIN = "https://site.test"
_INDEX = f"{_ORIGIN}/"
_ABOUT = f"{_ORIGIN}/about"
_PRODUCTS = f"{_ORIGIN}/products"
_DEEP = f"{_ORIGIN}/products/widget"
_EXTERNAL = "https://example.com/"

# forms + links each page exposes when ``browser.evaluate`` runs _DOM_ENUM_JS.
_SITE: dict[str, dict[str, object]] = {
    _INDEX: {
        "forms": [
            {
                "id": "contact",
                "action": f"{_ORIGIN}/contact",
                "method": "post",
                "fields": [
                    {"name": "name", "type": "text", "selector": "#name", "required": True},
                    {"name": "email", "type": "email", "selector": "#email", "required": True},
                    {"name": "msg", "type": "textarea", "selector": '[name="msg"]'},
                ],
                "submit_selector": "#contact-submit",
            },
            {
                "id": "login",
                "action": f"{_ORIGIN}/login",
                "method": "post",
                "fields": [
                    {"name": "user", "type": "email", "selector": "#user"},
                    {"name": "pass", "type": "password", "selector": "#pass"},
                ],
                "submit_selector": "#login-submit",
            },
        ],
        "links": [_ABOUT, _PRODUCTS, _EXTERNAL],
    },
    _ABOUT: {"forms": [], "links": [_INDEX]},
    _PRODUCTS: {
        "forms": [
            {
                "id": None,
                "action": None,
                "method": "get",
                "fields": [{"name": "q", "type": "search", "selector": "#q"}],
                "submit_selector": "form button[type=submit]",
            }
        ],
        "links": [_DEEP],
    },
    _DEEP: {"forms": [], "links": []},
}


class FakeInvoker:
    """Canned :class:`McpInvoker` stand-in. Stateful: tracks the navigated URL.

    ``browser.navigate`` records the page so the subsequent ``browser.evaluate``
    DOM enumeration can answer with that page's forms+links. Console-error reads
    always return an empty buffer.
    """

    def __init__(self, site: dict[str, dict[str, object]]) -> None:
        self._site = site
        self._current = ""
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def invoke(
        self,
        *,
        explicit_provider: str | None,
        tool: str,
        arguments: dict[str, object],
        ctx: InvokeContext,
    ) -> McpToolResult:
        self.calls.append((tool, arguments))
        if tool == "browser.navigate":
            self._current = str(arguments["url"])
            return McpToolResult(ok=True, output={"result": {"loaded": True}}, duration_ms=1)
        if tool == "browser.evaluate":
            expr = str(arguments.get("expression", ""))
            if "__suitest_console_errors__" in expr:
                return McpToolResult(ok=True, output={"result": []}, duration_ms=1)
            payload = self._site.get(self._current, {"forms": [], "links": []})
            return McpToolResult(ok=True, output={"result": payload}, duration_ms=1)
        return McpToolResult(ok=True, output={}, duration_ms=1)  # pragma: no cover


def _crawler(invoker: FakeInvoker, **opts: object) -> UrlCrawler:
    options = CrawlerOptions.model_validate(opts)
    # FakeInvoker is a structural stand-in for McpInvoker (only ``invoke`` used).
    return UrlCrawler(cast("McpInvoker", invoker), options, CrawlerAuthConfig())


async def _collect(crawler: UrlCrawler, start: str) -> list[TestCaseDraft]:
    return [draft async for draft in crawler.crawl(start, "ws-1")]


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_case_per_visited_page() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=3, max_pages=20), _INDEX)
    smoke = [d for d in drafts if d.generated_from["case_kind"] == "smoke"]
    urls = {d.generated_from["url"] for d in smoke}
    # index → about, products → products/widget. External dropped.
    assert urls == {_INDEX, _ABOUT, _PRODUCTS, _DEEP}
    # Each smoke case is navigate + assert-no-console-error.
    for d in smoke:
        assert [s.action.split()[0] for s in d.steps] == ["Navigate", "Assert"]


@pytest.mark.asyncio
async def test_form_cases_emitted_when_enabled() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=3, include_form_cases=True), _INDEX)
    forms = [d for d in drafts if d.generated_from["case_kind"] == "form"]
    # 2 forms on index + 1 on products = 3.
    assert len(forms) == 3
    labels = {d.generated_from["form_id"] for d in forms}
    assert "contact" in labels and "login" in labels


@pytest.mark.asyncio
async def test_no_form_cases_when_disabled() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=3, include_form_cases=False), _INDEX)
    assert all(d.generated_from["case_kind"] == "smoke" for d in drafts)


@pytest.mark.asyncio
async def test_respects_max_depth() -> None:
    inv = FakeInvoker(_SITE)
    # depth=1: index (0) → about/products (1). products/widget is depth 2 → dropped.
    drafts = await _collect(_crawler(inv, max_depth=1, include_form_cases=False), _INDEX)
    urls = {d.generated_from["url"] for d in drafts}
    assert urls == {_INDEX, _ABOUT, _PRODUCTS}
    assert _DEEP not in urls


@pytest.mark.asyncio
async def test_respects_max_pages() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(
        _crawler(inv, max_depth=3, max_pages=2, include_form_cases=False), _INDEX
    )
    smoke = [d for d in drafts if d.generated_from["case_kind"] == "smoke"]
    assert len(smoke) == 2


@pytest.mark.asyncio
async def test_same_origin_filter_drops_external() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(
        _crawler(inv, max_depth=3, same_origin_only=True, include_form_cases=False), _INDEX
    )
    urls = {d.generated_from["url"] for d in drafts}
    assert _EXTERNAL not in urls
    # The external page was never navigated.
    navigated = {a["url"] for t, a in inv.calls if t == "browser.navigate"}
    assert _EXTERNAL not in navigated


@pytest.mark.asyncio
async def test_every_step_references_playwright_mcp() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=3, include_form_cases=True), _INDEX)
    for d in drafts:
        assert d.target_kind.value == "FE_WEB"
        for step in d.steps:
            assert step.mcp_provider == "playwright-mcp"
            assert step.target_kind.value == "FE_WEB"


@pytest.mark.asyncio
async def test_faker_field_mapping() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=1, include_form_cases=True), _INDEX)
    fill_data = {
        s.data["selector"]: s.data
        for d in drafts
        if d.generated_from["case_kind"] == "form"
        for s in d.steps
        if s.data and "selector" in s.data and "value" in s.data
    }
    # email field → email-shaped value.
    assert re.match(r"[^@]+@[^@]+\.[^@]+", str(fill_data["#email"]["value"]))
    assert re.match(r"[^@]+@[^@]+\.[^@]+", str(fill_data["#user"]["value"]))
    # password field → 12-char value.
    assert len(str(fill_data["#pass"]["value"])) == 12
    # textarea/text → multi-word sentence (non-empty).
    assert str(fill_data['[name="msg"]']["value"])


@pytest.mark.asyncio
async def test_faker_reproducible_across_runs() -> None:
    a = await _collect(_crawler(FakeInvoker(_SITE), max_depth=1), _INDEX)
    b = await _collect(_crawler(FakeInvoker(_SITE), max_depth=1), _INDEX)

    def _values(drafts: list[TestCaseDraft]) -> list[object]:
        return [
            s.data["value"]
            for d in drafts
            if d.generated_from["case_kind"] == "form"
            for s in d.steps
            if s.data and "value" in s.data
        ]

    assert _values(a) == _values(b)


@pytest.mark.asyncio
async def test_tag_prefix_applied() -> None:
    inv = FakeInvoker(_SITE)
    drafts = await _collect(_crawler(inv, max_depth=1, tag_prefix="web-"), _INDEX)
    assert all(all(t.startswith("web-") for t in d.tags) for d in drafts)

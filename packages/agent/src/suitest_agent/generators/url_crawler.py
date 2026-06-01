"""Heuristic URL crawler generator (M2 Task 3).

Pure heuristics, NO LLM — runs in every tier. Given a start URL the crawler
drives the bundled ``playwright-mcp`` provider to BFS a site (bounded by
``max_depth`` / ``max_pages``), and for every visited page emits:

* one **smoke** :class:`~suitest_shared.schemas.generator_input.TestCaseDraft`
  — navigate → assert no console error, and
* (when ``options.include_form_cases``) one **form** draft per discovered
  ``<form>`` — navigate → fill each field with a Faker value chosen by the
  field type → submit → wait for navigation/success.

Frontier expansion uses the same-origin ``<a href>`` links discovered by the
DOM-enumeration eval; off-origin links are dropped when ``same_origin_only``.

playwright-mcp tool surface
---------------------------
We drive only tools the bundled provider actually advertises (see
:mod:`suitest_mcp.bundled.playwright` ``DECLARED_TOOLS``):

* ``browser.navigate`` — load a page.
* ``browser.evaluate`` — run JS in page context. Used both to enumerate
  forms+links (``_DOM_ENUM_JS``) and to read console errors collected on
  ``window.__suitest_console_errors__`` (``_CONSOLE_ERRORS_JS``).

The provider exposes **no** dedicated ``get_console_log`` tool, so the crawler
reads console errors via an ``evaluate`` of a window-attached error buffer; if
the page never installed the buffer the eval yields an empty list and the smoke
case simply asserts "no console error". The generated *step* code still routes
through ``playwright-mcp`` so the runner re-drives the same surface.

``Faker`` is seeded deterministically so an identical site graph yields
byte-identical fill values — a generated-case diff means the site changed, not
the RNG.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from faker import Faker
from suitest_shared.domain.enums import CaseSource, Priority, TargetKind
from suitest_shared.schemas.generator_input import (
    CrawlerAuthConfig,
    CrawlerOptions,
    TestCaseDraft,
    TestStepDraft,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from suitest_mcp.invoker import InvokeContext, McpInvoker

#: Provider every crawler step routes through (playwright-mcp, FE_WEB).
_PROVIDER = "playwright-mcp"

#: Deterministic Faker seed — reproducible fill values across runs.
_FAKER_SEED = 4242

#: JS evaluated to enumerate forms (+ their fields) and anchor hrefs on a page.
_DOM_ENUM_JS = """(() => ({
  forms: [...document.querySelectorAll('form')].map(f => ({
    id: f.id || null,
    action: f.action || null,
    method: f.method,
    fields: [...f.querySelectorAll('input, textarea, select')].map(el => ({
      name: el.name, type: el.type || el.tagName.toLowerCase(),
      selector: el.id ? '#' + el.id : `[name="${el.name}"]`,
      required: el.required, placeholder: el.placeholder,
    })),
    submit_selector: f.querySelector('[type=submit]')?.id
      ? '#' + f.querySelector('[type=submit]').id
      : 'form button[type=submit]'
  })),
  links: [...document.querySelectorAll('a[href]')].map(a => a.href),
}))()"""

#: JS evaluated to read console errors collected on a window buffer (best-effort).
_CONSOLE_ERRORS_JS = "(() => (window.__suitest_console_errors__ || []))()"


class UrlCrawler:
    """Stateful per-request crawler. Reusable across one ``crawl`` only."""

    def __init__(
        self,
        mcp_invoker: McpInvoker,
        options: CrawlerOptions,
        auth: CrawlerAuthConfig,
    ) -> None:
        self._mcp = mcp_invoker
        self._options = options
        self._auth = auth
        self._faker = Faker(options.faker_locale)
        self._faker.seed_instance(_FAKER_SEED)

    # ------------------------------------------------------------------

    async def crawl(self, start_url: str, workspace_id: str) -> AsyncIterator[TestCaseDraft]:
        """BFS from ``start_url``, yielding one smoke draft (+ form drafts) per page.

        Honors ``max_depth`` (links beyond it are never enqueued), ``max_pages``
        (visited cap), and ``same_origin_only`` (off-origin links dropped).
        """
        # Lazy import keeps the agent package import-light + avoids a hard dep
        # cycle (mcp imports shared; agent imports both at call time only).
        from suitest_mcp.invoker import InvokeContext

        origin = urlparse(start_url).hostname
        ctx = InvokeContext(
            workspace_id=workspace_id,
            target_kind=TargetKind.FE_WEB,
            actor_user_id=None,
        )

        queue: list[tuple[str, int]] = [(start_url, 0)]
        visited: set[str] = set()

        while queue and len(visited) < self._options.max_pages:
            url, depth = queue.pop(0)
            if url in visited or depth > self._options.max_depth:
                continue
            visited.add(url)

            await self._mcp.invoke(
                explicit_provider=_PROVIDER,
                tool="browser.navigate",
                arguments={"url": url, "wait_until": "networkidle"},
                ctx=ctx,
            )
            console_errors = await self._read_console_errors(ctx)
            yield self._smoke_case(url, console_errors)

            dom = await self._enumerate_dom(ctx)
            forms = _as_list(dom.get("forms"))
            links = _as_list(dom.get("links"))

            if self._options.include_form_cases:
                for index, form in enumerate(forms):
                    if isinstance(form, dict):
                        yield self._form_case(url, form, index)

            if depth + 1 <= self._options.max_depth:
                for link in links:
                    if not isinstance(link, str):
                        continue
                    if self._options.same_origin_only and urlparse(link).hostname != origin:
                        continue
                    if link not in visited:
                        queue.append((link, depth + 1))

    # ------------------------------------------------------------------

    async def _read_console_errors(self, ctx: InvokeContext) -> list[object]:
        """Best-effort console-error read via ``browser.evaluate`` (empty on miss)."""
        result = await self._mcp.invoke(
            explicit_provider=_PROVIDER,
            tool="browser.evaluate",
            arguments={"expression": _CONSOLE_ERRORS_JS},
            ctx=ctx,
        )
        return _as_list(_eval_payload(result).get("result"))

    async def _enumerate_dom(self, ctx: InvokeContext) -> dict[str, object]:
        """Enumerate forms + links via ``browser.evaluate`` of :data:`_DOM_ENUM_JS`."""
        result = await self._mcp.invoke(
            explicit_provider=_PROVIDER,
            tool="browser.evaluate",
            arguments={"expression": _DOM_ENUM_JS},
            ctx=ctx,
        )
        payload = _eval_payload(result).get("result")
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------

    def _tag(self, *parts: str) -> list[str]:
        prefix = self._options.tag_prefix
        tags = list(parts)
        return [f"{prefix}{t}" for t in tags] if prefix else tags

    def _smoke_case(self, url: str, console_errors: list[object]) -> TestCaseDraft:
        path = urlparse(url).path or "/"
        steps = [
            TestStepDraft(
                order=1,
                action=f"Navigate to {url}",
                expected="Page loads (HTTP 200, document ready)",
                code=(
                    "result = await mcp.browser.navigate("
                    f"url={url!r}, wait_until='networkidle')\n"
                    "assert result.ok"
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"url": url},
            ),
            TestStepDraft(
                order=2,
                action="Assert no console errors",
                expected="Console error buffer is empty",
                code=(
                    "errors = await mcp.browser.evaluate(expression="
                    f"{_CONSOLE_ERRORS_JS!r})\n"
                    "assert not errors.get('result'), errors"
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"expression": _CONSOLE_ERRORS_JS},
            ),
        ]
        return TestCaseDraft(
            name=f"Smoke: {path}",
            description=f"Auto-generated smoke check for {url} (navigate + console-error assertion).",
            priority=Priority.P2,
            source=CaseSource.HEURISTIC_CRAWL,
            target_kind=TargetKind.FE_WEB,
            tags=self._tag("smoke", "crawler"),
            generated_from={
                "case_kind": "smoke",
                "url": url,
                "console_errors_at_generation": len(console_errors),
            },
            steps=steps,
        )

    def _form_case(self, url: str, form: dict[str, object], index: int) -> TestCaseDraft:
        fields = _as_list(form.get("fields"))
        form_id = form.get("id")
        label = str(form_id) if isinstance(form_id, str) and form_id else f"form-{index + 1}"
        submit_selector = form.get("submit_selector")
        submit = (
            str(submit_selector)
            if isinstance(submit_selector, str) and submit_selector
            else "form button[type=submit]"
        )

        steps: list[TestStepDraft] = [
            TestStepDraft(
                order=1,
                action=f"Navigate to {url}",
                expected="Form page loads",
                code=(
                    "result = await mcp.browser.navigate("
                    f"url={url!r}, wait_until='networkidle')\n"
                    "assert result.ok"
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"url": url},
            )
        ]

        order = 2
        for field in fields:
            if not isinstance(field, dict):
                continue
            selector = field.get("selector")
            if not isinstance(selector, str) or not selector:
                continue
            field_type = str(field.get("type") or "text")
            value = self._fake_for_field(field_type)
            steps.append(
                TestStepDraft(
                    order=order,
                    action=f"Fill {selector} ({field_type})",
                    expected="Field accepts input",
                    code=(f"await mcp.browser.type(selector={selector!r}, text={value!r})"),
                    mcp_provider=_PROVIDER,
                    target_kind=TargetKind.FE_WEB,
                    data={"selector": selector, "type": field_type, "value": value},
                )
            )
            order += 1

        steps.append(
            TestStepDraft(
                order=order,
                action=f"Submit form via {submit}",
                expected="Form submits (navigation or success indicator)",
                code=(
                    f"await mcp.browser.click(selector={submit!r})\n"
                    "await mcp.browser.wait_for(state='networkidle')"
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"submit_selector": submit},
            )
        )

        return TestCaseDraft(
            name=f"Form: {label} @ {urlparse(url).path or '/'}",
            description=f"Auto-generated form-fill case for {label} on {url} (Faker-seeded).",
            priority=Priority.P2,
            source=CaseSource.HEURISTIC_CRAWL,
            target_kind=TargetKind.FE_WEB,
            tags=self._tag("form", "crawler"),
            generated_from={
                "case_kind": "form",
                "url": url,
                "form_id": label,
                "field_count": len([f for f in fields if isinstance(f, dict)]),
            },
            steps=steps,
        )

    # ------------------------------------------------------------------

    def _fake_for_field(self, field_type: str) -> str:
        """Map an HTML field type to a Faker-generated value (deterministic)."""
        kind = field_type.lower()
        if kind == "email":
            return self._faker.email()
        if kind == "password":
            return self._faker.password(length=12)
        if kind == "tel":
            return self._faker.phone_number()
        if kind in {"number", "range"}:
            return str(self._faker.random_int(min=1, max=100))
        if kind == "date":
            return self._faker.date()
        if kind == "url":
            return self._faker.url()
        if kind in {"text", "textarea", "search"}:
            return self._faker.sentence(nb_words=3)
        return self._faker.word()


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _eval_payload(result: object) -> dict[str, object]:
    """Normalize an :class:`McpToolResult` into the eval payload dict.

    Prefers ``.output`` (already-structured), else parses ``.stdout`` as JSON.
    A plain non-dict JSON value is wrapped as ``{"result": value}`` so callers
    can always read ``payload["result"]``.
    """
    output = getattr(result, "output", None)
    if isinstance(output, dict) and output:
        return output if "result" in output else {"result": output}
    stdout = getattr(result, "stdout", "") or ""
    if stdout:
        try:
            parsed = json.loads(stdout)
        except (ValueError, TypeError):
            return {"result": stdout}
        return parsed if isinstance(parsed, dict) and "result" in parsed else {"result": parsed}
    return {}

"""LLM bridge — lifecycle-side client for the Suitest LLM proxy.

The lifecycle never holds an LLM provider key. It calls
``POST /api/v1/llm/complete`` on the Suitest server (authenticated with the
same ``SUITEST_API_KEY`` used for publishing); the server runs the completion
against the workspace's active, AES-encrypted LLM config. No config / ZERO
tier → the server answers 409 and every entry point here degrades to ``None``
so the deterministic baseline keeps working.

Two capabilities:

* :meth:`RemoteLlmClient.propose_edge_cases` — real plan enrichment
  (implements the :class:`suitest_lifecycle.enrich.LlmClient` protocol).
* :meth:`RemoteLlmClient.generate_frontend_body` — TestSprite-style Playwright
  codegen: given a plan case + the crawled DOM digest, the model writes the
  ``async def _body(page)`` for apps that don't follow any testid convention.

The SDK import stays lazy so the lifecycle core remains stdlib-only.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from suitest_lifecycle.enrich import EdgeSuggestion
from suitest_lifecycle.models import Priority

if TYPE_CHECKING:
    from suitest_lifecycle.analyzers.crawl import CrawlResult
    from suitest_lifecycle.config import Config
    from suitest_lifecycle.models import CodeSummary, PlanCase

_PRIORITY = {"high": Priority.HIGH, "medium": Priority.MEDIUM, "low": Priority.LOW}

# The generated body runs inside the fixed exporter wrapper — these names are
# in scope. The model must use them and nothing else needs importing.
_CODEGEN_SYSTEM = """You are a senior QA automation engineer writing one Playwright (Python, async) test body.

Output ONLY Python code (no markdown fences, no prose) of exactly this shape:

async def _body(page):
    _begin("action", "<step description>")
    ...playwright actions...
    await _ok(page)
    _begin("assertion", "<what is verified>")
    ...expect(...) assertions...
    await _ok(page)

Contract (already in scope — do NOT import anything):
- page: playwright.async_api Page; expect: playwright's expect; TIMEOUT (ms)
- BASE_URL, USERNAME, PASSWORD: strings from config
- _begin(step_type, description): starts a recorded step ("action"/"assertion")
- await _ok(page): closes the current step (screenshot). EVERY step needs it.
- Do NOT call _login() unless the provided login selectors are data-testids.

Selector policy, in priority order:
1. data-testid from the provided page digest → page.get_by_test_id("...")
2. otherwise the digest's input name/placeholder/type → page.locator('input[name="..."]') / get_by_placeholder
3. otherwise button text → page.get_by_role("button", name="...")
Never invent selectors that are not derivable from the digest.
Keep it to 3-7 steps.
Assertion policy — assert ONLY what the planned steps demand, using observable outcomes:
- element visibility (expect(...).to_be_visible(timeout=TIMEOUT)), URL ("..." in page.url), row counts, visible text.
- NEVER assert focus, CSS, animation, or any behavior the digest/steps do not explicitly state.
- NEVER assert literal values you did not see in the digest — no guessed URLs, route names,
  user names, or emails. For navigation outcomes assert the URL CHANGED from the previous
  route (capture `before = page.url` first), or that a digest element became visible.
- For negative cases (invalid/empty input) assert: an error element is visible OR the URL did not change — nothing more.

API cheat-sheet — use ONLY these patterns (anything else risks a runtime error):
    await locator.fill("...") / await locator.click()
    await expect(locator).to_be_visible(timeout=TIMEOUT)
    await expect(locator).to_contain_text("...")
    n = await locator.count()
    before = page.url
    ...action...
    await page.wait_for_timeout(800)
    assert page.url != before          # navigation happened
    assert page.url == before          # stayed put
Forbidden (will crash): the `re` module (NOT in scope), expect(...).to_have_url(...),
page.wait_for_url(...) inside the body, calling a Locator like a function.
Placeholders/labels are ATTRIBUTES, not text — never assert them via to_contain_text;
assert the element is visible instead. Text assertions may use ONLY strings that appear
in a route's "visible text" sample, copied EXACTLY (matching is case-sensitive).
ALWAYS append .first to any get_by_text/get_by_role lookup you write yourself —
strict mode fails on multiple matches.
"""


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def _extract_json_array(text: str) -> list[object]:
    """Best-effort: find the first JSON array in the completion."""
    t = _strip_fences(text)
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(t[start : end + 1])
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


class LlmClientBase:
    """LLM capabilities built on a single ``_complete()`` seam.

    Every capability (edge-case proposal, PRD planning, frontend codegen) is
    backend-agnostic — it only calls ``self._complete``. Concrete backends
    (:class:`RemoteLlmClient`, :class:`SamplingLlmClient`) supply that one
    method; :class:`ChainedLlmClient` composes several. The existing convention
    (``_complete`` returns ``""`` on failure) is what powers the fallback chain.
    """

    def _complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 4096) -> str:
        raise NotImplementedError

    # -- enrichment (LlmClient protocol) --------------------------------------
    def propose_edge_cases(
        self, summary: CodeSummary, existing_titles: set[str]
    ) -> list[EdgeSuggestion]:
        endpoints = [f"{e.method} {e.path}" for e in summary.endpoints][:40]
        pages = [f"{p.route} ({'protected' if p.protected else 'public'})" for p in summary.pages][
            :40
        ]
        prompt = (
            "Propose up to 5 NEW high-value edge-case tests for this app.\n"
            f"Mode: {summary.mode.value}\n"
            f"Endpoints: {json.dumps(endpoints)}\n"
            f"Pages: {json.dumps(pages)}\n"
            f"Existing test titles (do NOT duplicate): {json.dumps(sorted(existing_titles))}\n\n"
            "Reply with ONLY a JSON array; each item:\n"
            '{"title": "snake_case_sentence", "description": "...", "category": "...",'
            ' "priority": "High|Medium|Low", "source_ref": "<METHOD /path or fe:llm /route>",'
            ' "steps": [["action", "..."], ["assertion", "..."]]}'
        )
        out: list[EdgeSuggestion] = []
        for item in _extract_json_array(self._complete(prompt, max_tokens=2048)):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip().lower().replace(" ", "_")
            if not title or title in existing_titles:
                continue
            steps_raw = item.get("steps")
            steps: list[tuple[str, str]] = []
            if isinstance(steps_raw, list):
                for s in steps_raw:
                    if isinstance(s, (list, tuple)) and len(s) == 2:
                        kind = "assertion" if str(s[0]).lower() == "assertion" else "action"
                        steps.append((kind, str(s[1])))
            if not steps:
                continue
            out.append(
                EdgeSuggestion(
                    archetype="llm",
                    title=title[:200],
                    description=str(item.get("description", ""))[:500],
                    category=str(item.get("category", "LLM"))[:60] or "LLM",
                    priority=_PRIORITY.get(str(item.get("priority", "")).lower(), Priority.MEDIUM),
                    source_ref=str(item.get("source_ref", "")) or "fe:llm /",
                    steps=steps,
                )
            )
            if len(out) >= 5:
                break
        return out

    # -- PRD-driven planning (TestSprite-parity upload flow) --------------------
    def plan_from_prd(
        self,
        prd_context: str,
        app_context: str,
        existing_titles: set[str],
        *,
        max_cases: int = 15,
        allow_mutation: bool = False,
    ) -> list[dict[str, object]]:
        """Turn an uploaded PRD (markdown) + the app's discovered reality into
        a semantic test plan. Returns raw case dicts; the caller builds
        PlanCases and generates code. Empty list = LLM unavailable/unusable →
        caller keeps the deterministic baseline.
        """
        mutation_rule = (
            "Mutating flows (create/update) ARE allowed when the PRD demands them."
            if allow_mutation
            else (
                "SAFE MODE: never propose destructive/mutating flows "
                "(no delete/publish/payment; creates only when clearly reversible)."
            )
        )
        prompt = (
            "You are planning UI tests for a web app from its product spec.\n\n"
            f"=== PRODUCT SPEC (uploaded PRD) ===\n{prd_context}\n\n"
            f"=== DISCOVERED APP REALITY (live DOM crawl) ===\n{app_context}\n\n"
            f"Existing test titles (do NOT duplicate): {json.dumps(sorted(existing_titles))}\n\n"
            f"Propose up to {max_cases} tests that VERIFY THE PRD'S REQUIREMENTS "
            "against the discovered routes/elements. Cover positive AND negative "
            "paths per requirement. Only reference routes that exist in the "
            "discovery. The app may be freshly installed (empty data) — prefer "
            "flows that hold in an empty state (empty-state visible, validation, "
            f"auth) or that create their own data first. {mutation_rule}\n\n"
            "Reply with ONLY a JSON array; each item:\n"
            '{"title": "snake_case_sentence", "description": "which PRD requirement '
            'this verifies", "category": "...", "priority": "High|Medium|Low", '
            '"route": "/discovered/route", '
            '"steps": [["action", "..."], ["assertion", "..."]]}'
        )
        out: list[dict[str, object]] = []
        for item in _extract_json_array(self._complete(prompt, max_tokens=6000)):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip().lower().replace(" ", "_")
            steps = item.get("steps")
            if not title or title in existing_titles or not isinstance(steps, list):
                continue
            existing_titles.add(title)
            out.append(item)
            if len(out) >= max_cases:
                break
        return out

    # -- frontend codegen ------------------------------------------------------
    def generate_frontend_body(self, case: PlanCase, dom_context: str) -> str | None:
        """Return validated ``async def _body(page)`` source, or None on failure."""
        prompt = (
            f"Test case: {case.title}\n"
            f"Intent: {case.description}\n"
            "Planned steps:\n"
            + "\n".join(f"- [{s.type}] {s.description}" for s in case.steps)
            + f"\n\nApp context (crawled live DOM):\n{dom_context}\n"
        )
        code = _strip_fences(self._complete(prompt, system=_CODEGEN_SYSTEM, max_tokens=3000))
        return code if _valid_body(code) else None


class RemoteLlmClient(LlmClientBase):
    """Tier 2: LLM via the Suitest server's ``/llm/complete`` proxy."""

    def __init__(self, api_url: str, token: str, workspace_id: str | None = None) -> None:
        self._api_url = api_url
        self._token = token
        self._workspace_id = workspace_id
        self._disabled = False  # flipped on 409/tier errors → deterministic fallback

    def _complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 4096) -> str:
        if self._disabled:
            return ""
        from suitest_lifecycle.http_client import SuitestAPIError, SuitestClient

        try:
            with SuitestClient(
                self._api_url,
                token=self._token,
                workspace_id=self._workspace_id or None,
                # Plan/codegen completions run long on slow gateways — the SDK
                # default (30s) regularly times out mid-generation.
                timeout=180.0,
            ) as client:
                return client.llm_complete(prompt, system=system, max_tokens=max_tokens)
        except SuitestAPIError as exc:  # 409 = no LLM (ZERO tier) → stop asking
            if getattr(exc, "status_code", None) == 409:
                self._disabled = True
            return ""
        except Exception:  # network hiccup — never fail the run over enrichment
            return ""


class SamplingLlmClient(LlmClientBase):
    """Tier 1: inference via MCP ``sampling/createMessage`` (user's model).

    Requires the connected MCP client to have advertised ``sampling`` at
    initialize. Any failure returns ``""`` so the chain falls to the next tier.
    """

    def __init__(self) -> None:
        self.last_model: str | None = None

    def _complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 4096) -> str:
        from suitest_lifecycle import sampling

        try:
            result = sampling.create_message(prompt, system=system, max_tokens=max_tokens)
        except sampling.SamplingError:
            return ""  # chain lanjut ke tingkat berikutnya
        self.last_model = result.model
        return result.text


class ChainedLlmClient(LlmClientBase):
    """Try each client in order; first non-empty answer wins."""

    def __init__(self, clients: list[LlmClientBase]) -> None:
        self._clients = clients

    def _complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 4096) -> str:
        for client in self._clients:
            answer = client._complete(prompt, system=system, max_tokens=max_tokens)
            if answer:
                return answer
        return ""


# Compiles fine but crashes at runtime — reject and fall back instead.
_RUNTIME_LANDMINES = (
    re.compile(r"\bre\."),  # `re` is not in the generated file's scope
    re.compile(r"\.to_have_url\("),  # models pass locators/invalid values here
    re.compile(r"page\.wait_for_url\("),  # bodies must use the before/after-url pattern
)


def _valid_body(code: str) -> bool:
    """Structural gate on LLM output — wrong shape falls back to deterministic."""
    if not code.startswith("async def _body(page):"):
        return False
    if "_ok(page)" not in code or "_begin(" not in code:
        return False
    if re.search(r"^\s*(import|from)\s", code, re.M):  # wrapper provides everything
        return False
    if any(rx.search(code) for rx in _RUNTIME_LANDMINES):
        return False
    try:
        compile(code, "<llm-body>", "exec")
    except SyntaxError:
        return False
    return True


def build_dom_context(crawl: CrawlResult | None, summary: CodeSummary) -> str:
    """Compact per-route digest the codegen prompt can rely on."""
    lines: list[str] = []
    if crawl is not None and crawl.login.email:
        lines.append(
            "Login selectors (data-testid): "
            f"email={crawl.login.email} password={crawl.login.password} "
            f"submit={crawl.login.submit} error={crawl.login.error or '-'}"
        )
    for p in summary.pages[:12]:
        lines.append(f"Route {p.route} ({'protected' if p.protected else 'public'}):")
        if crawl is not None:
            tids = crawl.page_testids.get(p.route, [])
            if tids:
                lines.append(f"  testids: {json.dumps(tids[:30])}")
            els = crawl.page_elements.get(p.route, {})
            if els.get("inputs"):
                lines.append(f"  inputs: {json.dumps(els['inputs'][:15])}")
            if els.get("buttons"):
                lines.append(f"  buttons: {json.dumps(els['buttons'][:15])}")
    return "\n".join(lines) or "No DOM digest available — rely on the planned steps only."


def build_dom_context_from_discovery(discovery: object) -> str:
    """Compact digest of a blackbox ``DiscoveryResult`` for codegen prompts."""
    from suitest_lifecycle.blackbox.models import DiscoveryResult
    from suitest_lifecycle.blackbox.selector import build_locator, describe

    if not isinstance(discovery, DiscoveryResult):
        return "No DOM digest available — rely on the planned steps only."
    lines: list[str] = []
    if discovery.login is not None and discovery.login.found():
        lines.append(
            "Login locators (Playwright expressions, ready to use): "
            f"username={discovery.login.username} password={discovery.login.password} "
            f"submit={discovery.login.submit}"
        )
        lines.append(
            "A helper `await _bb_login(page)` performing this login IS in scope — "
            "use it instead of re-implementing login."
        )
    for p in discovery.pages[:12]:
        lines.append(f"Route {p.route} (pattern={p.pattern}):")
        if p.row_locator:
            lines.append(f"  rows: {p.row_locator}")
        if p.search_locator:
            lines.append(f"  search: {p.search_locator}")
        for e in (p.inputs + p.buttons)[:14]:
            lines.append(f"  {e.kind or e.tag} '{describe(e)}': {build_locator(e)}")
        if p.visible_text_sample:
            sample = " ".join(p.visible_text_sample.split())[:280]
            lines.append(f"  visible text (assert ONLY strings occurring here): {sample}")
    return "\n".join(lines)[:14_000]


def resolve_remote(config: Config) -> RemoteLlmClient | None:
    """Build the proxy client from publish config / env; None when unreachable.

    Mirrors :mod:`suitest_lifecycle.publish` secret resolution: config wins,
    env (``SUITEST_API_URL`` / ``SUITEST_API_KEY``) fills the gaps.
    """
    api_url = config.publish.api_url or os.environ.get("SUITEST_API_URL", "")
    token = config.publish.token or os.environ.get("SUITEST_API_KEY", "")
    if not api_url or not token:
        return None
    return RemoteLlmClient(api_url, token, config.publish.workspace_id or None)


def resolve_llm(config: Config) -> LlmClientBase | None:
    """Assemble the LLM chain (spec P0 #2): sampling → bridge → None.

    Tier 1 is MCP sampling (the user's own model, no key) when the connected
    client advertised it. Tier 2 is the remote ``/llm/complete`` bridge (which
    also covers the BYO-key case server-side). When neither is available the
    caller keeps the deterministic baseline (returns ``None``).
    """
    from suitest_lifecycle import mcp_server

    clients: list[LlmClientBase] = []
    if mcp_server.client_supports_sampling():
        clients.append(SamplingLlmClient())
    remote = resolve_remote(config)
    if remote is not None:
        clients.append(remote)
    if not clients:
        return None
    return clients[0] if len(clients) == 1 else ChainedLlmClient(clients)


def describe_llm_source(client: object) -> dict[str, object]:
    """Where the generation's inference came from (for the envelope + analytics)."""
    if client is None:
        return {"llm_source": "deterministic", "model": None}
    if isinstance(client, ChainedLlmClient):
        for inner in client._clients:
            if isinstance(inner, SamplingLlmClient) and inner.last_model:
                return {"llm_source": "sampling", "model": inner.last_model}
        return {"llm_source": "bridge", "model": None}
    if isinstance(client, SamplingLlmClient):
        return {"llm_source": "sampling", "model": client.last_model}
    return {"llm_source": "bridge", "model": None}


__all__ = [
    "ChainedLlmClient",
    "LlmClientBase",
    "RemoteLlmClient",
    "SamplingLlmClient",
    "build_dom_context",
    "build_dom_context_from_discovery",
    "describe_llm_source",
    "resolve_llm",
    "resolve_remote",
]

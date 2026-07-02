"""No-repo frontend discovery via live DOM crawl (Playwright).

When QA has only a dev/staging URL (no source), Suitest drives a real browser to
discover the app: detect + perform login, then walk reachable routes recording
each page's interactive elements (inputs, buttons, links, data-testids) and the
login field selectors. Output feeds the frontend plan/exporter so generated UI
tests use the *discovered* selectors instead of source-derived ones.

Async (Playwright); :func:`analyze_crawl` is the sync entry the orchestrator calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from suitest_lifecycle.models import CodeSummary, Mode, Page

_EXTRACT_JS = """
() => {
  const sel = (el) => el.getAttribute('data-testid');
  const inputs = [...document.querySelectorAll('input,textarea,select')].map(e => ({
    testid: sel(e), type: e.getAttribute('type') || e.tagName.toLowerCase(),
    name: e.getAttribute('name') || '', placeholder: e.getAttribute('placeholder') || '',
    autocomplete: e.getAttribute('autocomplete') || ''
  }));
  const buttons = [...document.querySelectorAll('button,[role=button],input[type=submit]')].map(e => ({
    testid: sel(e), text: (e.innerText || e.value || '').trim().slice(0,40)
  }));
  const links = [...document.querySelectorAll('a[href]')].map(e => e.getAttribute('href'))
    .filter(h => h && h.startsWith('/'));
  const testids = [...document.querySelectorAll('[data-testid]')].map(sel);
  return { inputs, buttons, links: [...new Set(links)], testids: [...new Set(testids)] };
}
"""


@dataclass
class LoginSelectors:
    email: str = ""
    password: str = ""
    submit: str = ""
    error: str = ""


@dataclass
class CrawlResult:
    summary: CodeSummary
    login: LoginSelectors
    page_testids: dict[str, list[str]] = field(default_factory=dict)


def _pick_testid(items: list[dict], *needles: str) -> str:
    """Best data-testid match by needle in testid/name/type/autocomplete."""
    for it in items:
        hay = " ".join(
            str(it.get(k, "")) for k in ("testid", "name", "type", "autocomplete", "placeholder")
        ).lower()
        if it.get("testid") and all(n in hay for n in needles):
            return str(it["testid"])
    return ""


async def _crawl(base_url: str, username: str, password: str, max_pages: int) -> CrawlResult:
    from playwright.async_api import async_playwright

    base = base_url.rstrip("/")
    pages: list[Page] = []
    page_testids: dict[str, list[str]] = {}
    login = LoginSelectors()
    visited: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(base + "/", wait_until="networkidle")
        anon_url = page.url
        data = await page.evaluate(_EXTRACT_JS)

        # detect a login form (email + password inputs)
        email_sel = _pick_testid(data["inputs"], "email") or _pick_testid(data["inputs"], "user")
        pwd_sel = _pick_testid(data["inputs"], "password")
        if email_sel and pwd_sel:
            login.email = email_sel
            login.password = pwd_sel
            login.submit = (
                _pick_testid(data["buttons"], "submit")
                or _pick_testid(data["buttons"], "login")
                or _pick_testid(data["buttons"], "sign")
            )
            login.error = _pick_testid(data["inputs"], "error") or ""
            route = _route_of(anon_url, base)
            pages.append(Page(route=route or "/login", name="LoginPage", protected=False, source_file="crawl"))
            page_testids[route or "/login"] = data["testids"]

            # perform login
            if username and password and login.submit:
                await page.get_by_test_id(login.email).fill(username)
                await page.get_by_test_id(login.password).fill(password)
                await page.get_by_test_id(login.submit).click()
                # SPA: the route changes client-side — wait for the URL to leave
                # /login (any new route) rather than a network event.
                try:
                    await page.wait_for_url(lambda u: "/login" not in u, timeout=8000)
                except Exception:
                    pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass

        # collect reachable internal routes (post-login)
        after = await page.evaluate(_EXTRACT_JS)
        home = _route_of(page.url, base)
        queue = list(dict.fromkeys([home, *after["links"]]))
        for href in queue:
            if len(visited) >= max_pages:
                break
            if not href or href in visited:
                continue
            visited.add(href)
            try:
                await page.goto(base + href, wait_until="networkidle", timeout=8000)
            except Exception:
                continue
            landed = _route_of(page.url, base)
            d = await page.evaluate(_EXTRACT_JS)
            protected = landed != href and ("login" in landed.lower())  # redirected to login
            name = _name_of(href)
            if not any(pg.route == href for pg in pages):
                pages.append(Page(route=href, name=name, protected=not protected and href != "/login", source_file="crawl"))
            page_testids[href] = d["testids"]
            for ln in d["links"]:
                if ln not in visited and len(queue) < max_pages * 2:
                    queue.append(ln)

        await browser.close()

    summary = CodeSummary(
        project_name="crawled-frontend",
        mode=Mode.FRONTEND,
        tech_stack=["Web", "crawled"],
        pages=pages,
        features=[p.name for p in pages],
        auth_flow="Login form discovered via DOM crawl." if login.email else "No login form found.",
    )
    return CrawlResult(summary=summary, login=login, page_testids=page_testids)


def _route_of(url: str, base: str) -> str:
    tail = url[len(base):] if url.startswith(base) else url
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    return tail or "/"


def _name_of(route: str) -> str:
    parts = [p for p in route.strip("/").split("/") if p and not p.startswith(":")]
    return ("".join(s.capitalize() for s in parts) or "Root") + "Page"


def analyze_crawl(base_url: str, username: str, password: str, max_pages: int = 12) -> CrawlResult:
    return asyncio.run(_crawl(base_url, username, password, max_pages))


__all__ = ["CrawlResult", "LoginSelectors", "analyze_crawl"]

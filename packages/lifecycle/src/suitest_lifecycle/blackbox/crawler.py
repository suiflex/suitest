"""Blackbox crawler — open a real browser, log in, walk the app, capture evidence.

No repo, no LLM, no testid requirement. Per page it records: interactive
elements (rich attributes for the selector strategy), pattern classification,
screenshot, console errors, network failures, and blank/crash detection.
SafeMode (default ON) refuses to follow destructive links (logout, delete,
billing, payment, …).

Async Playwright; :func:`discover` is the sync entry every consumer calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from suitest_lifecycle.blackbox.detector import detect_login_form, detect_page_pattern
from suitest_lifecycle.blackbox.models import (
    BlackboxUiConfig,
    DiscoveryResult,
    ElementInfo,
    LoginProbe,
    PageInfo,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

# Rich per-element capture: every attribute the selector strategy ranks.
_EXTRACT_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labelFor = (el) => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const wrap = el.closest('label'); return wrap ? wrap.innerText.trim().slice(0, 80) : '';
  };
  const cssPath = (el) => {
    const parts = [];
    let cur = el;
    for (let i = 0; cur && cur.nodeType === 1 && i < 5; i++) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift(`#${cur.id}`); break; }
      const sibs = cur.parentElement ? [...cur.parentElement.children].filter(c => c.tagName === cur.tagName) : [];
      if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(cur) + 1})`;
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  };
  const info = (el, kind) => ({
    tag: el.tagName.toLowerCase(),
    kind,
    testid: el.getAttribute('data-testid') || el.getAttribute('data-cy') || el.getAttribute('data-test') || '',
    testid_attr: el.hasAttribute('data-testid') ? 'data-testid' : el.hasAttribute('data-cy') ? 'data-cy' : el.hasAttribute('data-test') ? 'data-test' : '',
    role: el.getAttribute('role') || '',
    aria_label: el.getAttribute('aria-label') || '',
    label: labelFor(el),
    placeholder: el.getAttribute('placeholder') || '',
    name: el.getAttribute('name') || '',
    input_type: (el.getAttribute('type') || '').toLowerCase(),
    autocomplete: el.getAttribute('autocomplete') || '',
    text: (el.innerText || el.value || '').trim().slice(0, 80),
    dom_id: el.id || '',
    href: el.getAttribute && el.tagName === 'A' ? (el.getAttribute('href') || '') : '',
    css: cssPath(el),
    required: el.required === true || el.getAttribute('aria-required') === 'true',
  });
  const inputs = [...document.querySelectorAll('input,textarea,select')].filter(vis).map(e => info(e, e.tagName === 'SELECT' ? 'select' : (e.type === 'checkbox' ? 'checkbox' : 'input')));
  const buttons = [...document.querySelectorAll('button,[role=button],input[type=submit],a[role=button]')].filter(vis).map(e => info(e, 'button'));
  const links = [...document.querySelectorAll('a[href]')].filter(vis).map(e => info(e, 'link')).filter(l => l.href.startsWith('/'));
  const tables = document.querySelectorAll('table tbody tr, [role=row], [role=grid] [role=row]');
  let rowSelector = '';
  if (document.querySelector('table tbody tr')) rowSelector = 'table tbody tr';
  else if (document.querySelector('[role=grid] [role=row]')) rowSelector = '[role=grid] [role=row]';
  // repeated-testid rows (list rendered as divs)
  const counts = {};
  document.querySelectorAll('[data-testid]').forEach(e => { const t = e.getAttribute('data-testid'); counts[t] = (counts[t] || 0) + 1; });
  const repeated = Object.entries(counts).filter(([, n]) => n >= 3).sort((a, b) => b[1] - a[1]);
  if (!rowSelector && repeated.length) rowSelector = `[data-testid="${repeated[0][0]}"]`;
  const search = [...document.querySelectorAll('input[type=search],input[placeholder]')].filter(vis)
    .find(e => /search|cari|filter/i.test((e.getAttribute('placeholder') || '') + (e.getAttribute('name') || '') + (e.getAttribute('aria-label') || '')));
  const pager = [...document.querySelectorAll('button,a')].filter(vis)
    .find(e => /next|»|older|selanjutnya/i.test((e.innerText || '').trim()) || (e.getAttribute('aria-label') || '').match(/next page/i));
  return {
    title: document.title || '',
    inputs, buttons, links,
    testids: [...new Set([...document.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')))],
    hasTable: tables.length >= 1 || !!rowSelector,
    rowSelector,
    hasModal: !!document.querySelector('[role=dialog],[aria-modal=true],dialog[open]'),
    searchInfo: search ? info(search, 'input') : null,
    pagerInfo: pager ? info(pager, 'button') : null,
    textSample: (document.body ? document.body.innerText : '').trim().slice(0, 1500),
    elementCount: document.body ? document.body.querySelectorAll('*').length : 0,
  };
}
"""

_SAFE_SKIP_HREF = re.compile(
    r"(logout|log-out|sign-?out|delete|remove|destroy|billing|payment|checkout|subscribe"
    r"|unsubscribe|deactivate)",
    re.I,
)


async def _goto(page: Page, url: str) -> None:
    """Navigate like the real internet works: DOMContentLoaded is the contract;
    networkidle is only a short best-effort settle (analytics/long-polling on
    public sites keep the network busy forever)."""
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=3000)


def _route_of(url: str, base: str) -> str:
    tail = url[len(base) :] if url.startswith(base) else url
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    return tail or "/"


def _excluded(route: str, cfg: BlackboxUiConfig) -> bool:
    if any(route.startswith(x) for x in cfg.crawl.exclude):
        return True
    if cfg.crawl.include and not any(route.startswith(x) for x in cfg.crawl.include):
        return True
    return bool(cfg.crawl.safe_mode and _SAFE_SKIP_HREF.search(route))


async def _snapshot(
    page: Page,
    route: str,
    depth: int,
    evidence_dir: Path,
    console_errors: list[str],
    network_errors: list[str],
    *,
    shot_name: str,
) -> PageInfo:
    data = await page.evaluate(_EXTRACT_JS)
    shot = ""
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 — tiny, one-off, local FS
        shot_path = evidence_dir / f"{shot_name}.png"
        await page.screenshot(path=str(shot_path))
        shot = str(shot_path)
    except Exception:  # screenshot must never sink the crawl
        shot = ""
    info = PageInfo(
        route=route,
        url=page.url,
        title=str(data.get("title", "")),
        depth=depth,
        inputs=[ElementInfo.from_json(e) for e in data.get("inputs", [])],
        buttons=[ElementInfo.from_json(e) for e in data.get("buttons", [])],
        links=[ElementInfo.from_json(e) for e in data.get("links", [])],
        nav_routes=sorted({str(e.get("href", "")) for e in data.get("links", []) if e.get("href")}),
        testids=[str(t) for t in data.get("testids", [])],
        has_table=bool(data.get("hasTable")),
        row_locator=(
            f"page.locator('{data.get('rowSelector')}')" if data.get("rowSelector") else ""
        ),
        has_modal=bool(data.get("hasModal")),
        console_errors=list(console_errors),
        network_errors=list(network_errors),
        screenshot=shot,
        visible_text_sample=str(data.get("textSample", "")),
        blank=int(data.get("elementCount", 0)) < 5 or not str(data.get("textSample", "")).strip(),
    )
    from suitest_lifecycle.blackbox.selector import build_locator

    if data.get("searchInfo"):
        info.search_locator = build_locator(ElementInfo.from_json(data["searchInfo"]))
    if data.get("pagerInfo"):
        info.pagination_locator = build_locator(ElementInfo.from_json(data["pagerInfo"]))
    info.pattern = detect_page_pattern(info)
    info.has_form = info.pattern == "form" or (
        len([e for e in info.inputs if e.input_type not in ("checkbox", "radio", "hidden")]) >= 2
        and bool(info.buttons)
    )
    return info


async def _discover(cfg: BlackboxUiConfig, evidence_dir: Path) -> DiscoveryResult:
    from playwright.async_api import async_playwright

    base = cfg.target_url.rstrip("/")
    result = DiscoveryResult(base_url=base)
    console_errors: list[str] = []
    network_errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not cfg.headed)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        page.on(
            "console",
            lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(str(e)[:300]))
        page.on(
            "response",
            lambda r: network_errors.append(f"{r.status} {r.url[:200]}") if r.status >= 500 else None,
        )
        page.on(
            "requestfailed",
            # ERR_ABORTED = request cancelled by navigation (Next.js RSC
            # prefetch, analytics beacons) — normal behavior, not a bug signal.
            lambda r: (
                network_errors.append(f"FAILED {r.url[:200]} {r.failure or ''}")
                if "ERR_ABORTED" not in str(r.failure or "")
                else None
            ),
        )

        # ---- 1. login page ---------------------------------------------------
        login_route = cfg.auth.login_url or "/login"
        try:
            await _goto(page, base + login_route)
        except Exception:
            try:
                await _goto(page, base + "/")
            except Exception as exc:
                result.errors.append(f"target unreachable: {exc}")
                await browser.close()
                return result
        login_route = _route_of(page.url, base)
        console_errors.clear()
        network_errors.clear()
        login_page = await _snapshot(
            page, login_route, 0, evidence_dir, console_errors, network_errors, shot_name="login"
        )
        result.pages.append(login_page)

        form = detect_login_form(login_page, ignore_testids=cfg.crawl.ignore_testids)
        # manual overrides beat detection (docs: selectors.loginUsername/…)
        if cfg.selectors.login_username:
            form.username = _as_locator(cfg.selectors.login_username)
        if cfg.selectors.login_password:
            form.password = _as_locator(cfg.selectors.login_password)
        if cfg.selectors.login_submit:
            form.submit = _as_locator(cfg.selectors.login_submit)
        result.login = form if form.found() else None

        # ---- 2. perform login -------------------------------------------------
        if result.login and cfg.auth.username and cfg.auth.password:
            probe = LoginProbe(attempted=True)
            try:
                await _eval_locator(page, form.username).fill(cfg.auth.username)
                await _eval_locator(page, form.password).fill(cfg.auth.password)
                await _eval_locator(page, form.submit).click()
                with contextlib.suppress(Exception):
                    await page.wait_for_url(
                        lambda u: _route_of(u, base) != login_route, timeout=10000
                    )
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=5000)
                landed = _route_of(page.url, base)
                probe.landed_route = landed
                probe.success = landed != login_route
                if not probe.success:
                    # still on login — look for an error region to report
                    err = await page.evaluate(
                        "() => { const e = document.querySelector('[role=alert],"
                        "[class*=error],[data-testid*=error]');"
                        " return e ? (e.innerText || '').slice(0, 120) : ''; }"
                    )
                    probe.detail = f"stayed on {landed}; error: {err or 'none shown'}"
            except Exception as exc:
                probe.detail = f"login interaction failed: {exc}"[:300]
            result.login_probe = probe
        elif result.login:
            result.login_probe = LoginProbe(attempted=False, detail="no credentials configured")

        # ---- 3. BFS crawl ------------------------------------------------------
        # Seed from everywhere we already know: where we landed, the root, the
        # nav links captured on the entry page, and config includes. Without
        # this, an app with no /login (entry 404s) would dead-end immediately.
        start_route = _route_of(page.url, base)
        seeds = [start_route, "/", *login_page.nav_routes, *cfg.crawl.include]
        queue: list[tuple[str, int]] = [(r, 0) for r in dict.fromkeys(seeds)]
        visited: set[str] = {login_route}
        while queue and len(result.pages) < cfg.crawl.max_routes:
            route, depth = queue.pop(0)
            if route in visited or depth > cfg.crawl.max_depth:
                continue
            if _excluded(route, cfg) and route != start_route:
                result.skipped_routes.append(route)
                continue
            visited.add(route)
            console_errors.clear()
            network_errors.clear()
            try:
                await _goto(page, base + route)
            except Exception as exc:
                result.errors.append(f"{route}: navigation failed: {exc}"[:200])
                continue
            landed = _route_of(page.url, base)
            info = await _snapshot(
                page,
                route,
                depth,
                evidence_dir,
                console_errors,
                network_errors,
                shot_name=_shot_name(route),
            )
            info.protected = landed != route and "login" in landed.lower()
            result.pages.append(info)
            for href in info.nav_routes:
                if href not in visited and len(queue) < cfg.crawl.max_routes * 3:
                    queue.append((href, depth + 1))

        await browser.close()
    return result


def _shot_name(route: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", route).strip("_") or "root"
    return f"page_{slug}"[:80]


def _as_locator(expr: str) -> str:
    """Accept either a full ``page.…`` expression or a raw CSS selector."""
    e = expr.strip()
    return e if e.startswith("page.") else f'page.locator("{e}")'


def _eval_locator(page: Page, expr: str):
    """Resolve a stored locator EXPRESSION on a live page.

    The expression grammar is our own output (``build_locator``/`_as_locator``),
    so evaluating it against the page object is safe and keeps one single
    source of truth between discovery-time interaction and generated code.
    """
    return eval(expr, {"page": page})


def discover(cfg: BlackboxUiConfig, evidence_dir: str | Path) -> DiscoveryResult:
    """Sync entry: full blackbox discovery (login + crawl + evidence)."""
    return asyncio.run(_discover(cfg, Path(evidence_dir)))


async def _analyze_one(cfg: BlackboxUiConfig, url: str, evidence_dir: Path) -> PageInfo:
    from playwright.async_api import async_playwright

    base = cfg.target_url.rstrip("/") or url
    console_errors: list[str] = []
    network_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not cfg.headed)
        page = await (await browser.new_context(viewport={"width": 1280, "height": 720})).new_page()
        page.on(
            "console",
            lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(str(e)[:300]))
        target = url if url.startswith("http") else base + url
        await _goto(page, target)
        route = _route_of(page.url, base)
        info = await _snapshot(
            page,
            route,
            0,
            evidence_dir,
            console_errors,
            network_errors,
            shot_name=_shot_name(route),
        )
        await browser.close()
    return info


def analyze_single_page(cfg: BlackboxUiConfig, url: str, evidence_dir: str | Path) -> PageInfo:
    """Sync entry: analyze ONE page (pattern + elements + evidence), no crawl."""
    return asyncio.run(_analyze_one(cfg, url, Path(evidence_dir)))


__all__ = ["analyze_single_page", "discover"]

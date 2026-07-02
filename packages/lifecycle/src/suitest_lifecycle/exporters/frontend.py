"""Render runnable frontend ``TCxxx.py`` files (Playwright async) with recording.

Matches the TestSprite detail view: structured async session (chromium launch
args, ``new_context``, ``set_default_timeout(15000)``), one block per step, a
**video** recorded per test (``record_video_dir``), a per-step trace + final
screenshot written to a ``<TC>.result.json`` sidecar. Each file is standalone;
Suitest provides the browser (user installs nothing).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config
    from suitest_lifecycle.models import CodeSummary, PlanCase
    from suitest_lifecycle.paths import Paths

_HEADER = """import asyncio
import glob
import json
import os
import uuid

from playwright.async_api import async_playwright, expect

BASE_URL = "{base_url}"
USERNAME = "{username}"
PASSWORD = "{password}"
TIMEOUT = 15000
TC_ID = "{cid}"

# --- evidence pacing (watchable, step-by-step video) -------------------------
# The lifecycle video is human EVIDENCE, so it must NOT run at machine speed.
# We hold each step on screen (``_STEP_PAUSE_MS``) and slow every Playwright
# action (``_SLOWMO_MS``) so the recording reads step-by-step. Defaults are on;
# set SUITEST_EVIDENCE_RECORDING=false (or the pause to 0) for a fast run.
_EVIDENCE = os.environ.get("SUITEST_EVIDENCE_RECORDING", "true").lower() not in ("0", "false", "no")
_STEP_PAUSE_MS = int(os.environ.get("SUITEST_EVIDENCE_PAUSE_MS", "1200"))
_SLOWMO_MS = int(os.environ.get("SUITEST_EVIDENCE_SLOWMO_MS", "300"))

_HERE = os.path.dirname(os.path.abspath(__file__))
_TMP = os.path.join(_HERE, "tmp")
_VIDEO_DIR = os.path.join(_TMP, "videos", TC_ID)
_RESULT = os.path.join(_HERE, TC_ID + ".result.json")

# --- per-step recorder (feeds the web Steps panel) ---------------------------
STEPS = []
_cur = {{"index": 0, "type": "action", "description": ""}}
_N = [0]


def _begin(step_type, description):
    _N[0] += 1
    _cur.update(index=_N[0], type=step_type, description=description)


async def _shot(page):
    # Per-step screenshot — powers the web "Preview: Step N" (TestSprite parity).
    path = os.path.join(_TMP, TC_ID + "_step" + str(_cur["index"]) + ".png")
    try:
        os.makedirs(_TMP, exist_ok=True)
        await page.screenshot(path=path)
        return path
    except Exception:
        return ""


async def _ok(page):
    shot = await _shot(page)
    # Hold the finished step on screen so the recorded video reads step-by-step
    # instead of flashing past in ~1s. Screenshot is taken BEFORE the hold so it
    # captures the step's end state, not the idle pause.
    if _EVIDENCE and _STEP_PAUSE_MS > 0:
        try:
            await page.wait_for_timeout(_STEP_PAUSE_MS)
        except Exception:
            pass
    STEPS.append(dict(_cur, status="PASSED", screenshot=shot))


async def _login(page):
    # Authenticate through the real login form.
    _begin("action", "Navigate to /login")
    await page.goto(f"{{BASE_URL}}/login")
    await _ok(page)
    _begin("action", f"Fill '{{USERNAME}}' into the email field")
    await page.get_by_test_id("login-email-input").fill(USERNAME)
    await _ok(page)
    _begin("action", "Fill the password field")
    await page.get_by_test_id("login-password-input").fill(PASSWORD)
    await _ok(page)
    _begin("action", "Click 'Sign in'")
    await page.get_by_test_id("login-submit-button").click()
    await _ok(page)
    _begin("assertion", "Dashboard is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""

_RUNNER = """

async def run_test():
    pw = browser = context = page = None
    status = "PASSED"
    error = ""
    screenshot = os.path.join(_TMP, TC_ID + "_final.png")
    try:
        os.makedirs(_VIDEO_DIR, exist_ok=True)
        # Start a Playwright session in asynchronous mode.
        pw = await async_playwright().start()
        # Launch a Chromium browser in headless mode with custom arguments.
        browser = await pw.chromium.launch(
            headless=True,
            # slow_mo delays each action so intra-step motion (typing, clicks,
            # navigation) is visible in the recorded video, not just the gaps.
            slow_mo=_SLOWMO_MS if _EVIDENCE else 0,
            args=["--window-size=1280,720", "--disable-dev-shm-usage", "--ipc=host"],
        )
        # Create a new browser context that records video of the whole run.
        context = await browser.new_context(
            record_video_dir=_VIDEO_DIR, viewport={"width": 1280, "height": 720}
        )
        # Wider default timeout so auto-waiting Playwright APIs inherit it.
        context.set_default_timeout(TIMEOUT)
        page = await context.new_page()
        await _body(page)
        # Hold the final state so the video's last frames aren't clipped when the
        # context closes (Playwright stops recording on context.close()).
        if _EVIDENCE and _STEP_PAUSE_MS > 0:
            try:
                await page.wait_for_timeout(_STEP_PAUSE_MS)
            except Exception:
                pass
        try:
            await page.screenshot(path=screenshot)
        except Exception:
            pass
    except Exception as exc:  # record the failing step + capture a screenshot
        status = "FAILED"
        error = str(exc)
        _fail_shot = ""
        if page is not None:
            try:
                _fail_shot = os.path.join(_TMP, TC_ID + "_step" + str(_cur["index"]) + ".png")
                await page.screenshot(path=_fail_shot)
            except Exception:
                _fail_shot = ""
            try:
                await page.screenshot(path=screenshot)
            except Exception:
                pass
        STEPS.append(dict(_cur, status="FAILED", screenshot=_fail_shot))
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass
        vids = sorted(glob.glob(os.path.join(_VIDEO_DIR, "*.webm")))
        with open(_RESULT, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "testId": TC_ID,
                    "status": status,
                    "error": error,
                    "steps": STEPS,
                    "video": vids[-1] if vids else None,
                    "screenshot": screenshot if os.path.exists(screenshot) else None,
                },
                fh,
            )
    if status != "PASSED":
        raise AssertionError(error or "test failed")


if __name__ == "__main__":
    asyncio.run(run_test())
    print("PASS " + TC_ID)
"""


def _body(case: PlanCase) -> str:
    arch = case.source_ref.split(" ", 1)[0].replace("fe:", "")
    route = case.source_ref.split(" ", 1)[1] if " " in case.source_ref else "/"

    if arch == "login_success":
        return """
async def _body(page):
    await _login(page)
    _begin("assertion", "Dashboard summary is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "invalid_login":
        return """
async def _body(page):
    _begin("action", "Navigate to /login")
    await page.goto(f"{BASE_URL}/login")
    await _ok(page)
    _begin("action", "Fill an invalid password")
    await page.get_by_test_id("login-email-input").fill(USERNAME)
    await page.get_by_test_id("login-password-input").fill("wrong-password-xyz")
    await _ok(page)
    _begin("action", "Click 'Sign in'")
    await page.get_by_test_id("login-submit-button").click()
    await _ok(page)
    _begin("assertion", "An error message is shown and the URL stays /login")
    await expect(page.get_by_test_id("login-error-message")).to_be_visible(timeout=TIMEOUT)
    assert "/login" in page.url
    await _ok(page)
"""
    if arch == "protected_redirect":
        return f"""
async def _body(page):
    _begin("action", "Navigate directly to {route} with no session")
    await page.goto(f"{{BASE_URL}}{route}")
    await _ok(page)
    _begin("assertion", "Login page is shown")
    await expect(page.get_by_test_id("login-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "dashboard_loads":
        return """
async def _body(page):
    await _login(page)
    _begin("assertion", "Dashboard summary is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "products_list":
        return """
async def _body(page):
    await _login(page)
    _begin("action", "Open /products")
    await page.goto(f"{BASE_URL}/products")
    await _ok(page)
    _begin("assertion", "Products page is visible")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "search_empty":
        return """
async def _body(page):
    await _login(page)
    _begin("action", "Open /products")
    await page.goto(f"{BASE_URL}/products")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    _begin("action", "Type an unlikely search query")
    await page.get_by_test_id("product-search-input").fill("zzz-no-such-" + uuid.uuid4().hex[:6])
    await page.wait_for_timeout(600)
    await _ok(page)
    _begin("assertion", "No matching rows are shown")
    assert await page.get_by_test_id("product-row").count() == 0
    await _ok(page)
"""
    if arch == "create_product":
        return """
async def _body(page):
    await _login(page)
    _begin("action", "Open the product create form")
    await page.goto(f"{BASE_URL}/products/new")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    token = uuid.uuid4().hex[:8]
    _begin("action", "Fill the required product fields")
    await page.get_by_test_id("product-name-input").fill(f"Suitest Product {token}")
    await page.get_by_test_id("product-sku-input").fill(f"SKU-{token}")
    await page.get_by_test_id("product-price-input").fill("19.99")
    await page.get_by_test_id("product-stock-input").fill("5")
    await _ok(page)
    _begin("action", "Submit the form")
    await page.get_by_test_id("product-submit-button").click()
    await _ok(page)
    _begin("assertion", "Returns to the products list")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "empty_login":
        return """
async def _body(page):
    _begin("action", "Navigate to /login")
    await page.goto(f"{BASE_URL}/login")
    await _ok(page)
    _begin("action", "Click 'Sign in' with both fields empty")
    await page.get_by_test_id("login-submit-button").click()
    await _ok(page)
    _begin("assertion", "A validation error is shown and the URL stays /login")
    await expect(page.get_by_test_id("login-error-message")).to_be_visible(timeout=TIMEOUT)
    assert "/login" in page.url
    await _ok(page)
"""
    if arch == "logout":
        return """
async def _body(page):
    await _login(page)
    _begin("action", "Click the logout button")
    await page.get_by_test_id("logout-button").click()
    await _ok(page)
    _begin("assertion", "Login page is shown")
    await expect(page.get_by_test_id("login-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    _begin("action", "Navigate to /dashboard again")
    await page.goto(f"{BASE_URL}/dashboard")
    await _ok(page)
    _begin("assertion", "Still on the login page (session cleared)")
    await expect(page.get_by_test_id("login-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
"""
    if arch == "search_match":
        return """
async def _body(page):
    await _login(page)
    token = uuid.uuid4().hex[:8]
    name = f"Suitest Match {token}"
    _begin("action", "Create a uniquely-named product via the form")
    await page.goto(f"{BASE_URL}/products/new")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    await page.get_by_test_id("product-name-input").fill(name)
    await page.get_by_test_id("product-sku-input").fill(f"SKU-{token}")
    await page.get_by_test_id("product-price-input").fill("9.99")
    await page.get_by_test_id("product-stock-input").fill("3")
    await page.get_by_test_id("product-submit-button").click()
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    _begin("action", "Search for the exact product name")
    await page.get_by_test_id("product-search-input").fill(name)
    await page.wait_for_timeout(600)
    await _ok(page)
    _begin("assertion", "Exactly the matching product row is shown")
    rows = page.get_by_test_id("product-row")
    assert await rows.count() == 1, f"expected 1 matching row, got {await rows.count()}"
    await expect(rows.first).to_contain_text(name)
    await _ok(page)
"""
    if arch == "delete_product":
        return """
async def _body(page):
    await _login(page)
    token = uuid.uuid4().hex[:8]
    name = f"Suitest Delete {token}"
    _begin("action", "Create a uniquely-named product via the form")
    await page.goto(f"{BASE_URL}/products/new")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    await page.get_by_test_id("product-name-input").fill(name)
    await page.get_by_test_id("product-sku-input").fill(f"SKU-{token}")
    await page.get_by_test_id("product-price-input").fill("9.99")
    await page.get_by_test_id("product-stock-input").fill("3")
    await page.get_by_test_id("product-submit-button").click()
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    _begin("action", "Search for it and delete it, accepting the confirm dialog")
    await page.get_by_test_id("product-search-input").fill(name)
    await page.wait_for_timeout(600)
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
    await page.get_by_test_id("product-delete-button").first.click()
    await page.wait_for_timeout(800)
    await _ok(page)
    _begin("assertion", "The product row disappears from the list")
    await page.get_by_test_id("product-search-input").fill(name)
    await page.wait_for_timeout(600)
    assert await page.get_by_test_id("product-row").count() == 0, "deleted product still listed"
    await _ok(page)
"""
    if arch == "create_invalid":
        return """
async def _body(page):
    await _login(page)
    _begin("action", "Open the product create form")
    await page.goto(f"{BASE_URL}/products/new")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    await _ok(page)
    _begin("action", "Fill a too-short name and no SKU, then submit")
    await page.get_by_test_id("product-name-input").fill("ab")
    await page.get_by_test_id("product-submit-button").click()
    await page.wait_for_timeout(600)
    await _ok(page)
    _begin("assertion", "Form stays visible with validation errors; no navigation")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    assert "/products/new" in page.url, f"unexpected navigation to {page.url}"
    await _ok(page)
"""
    return f"""
async def _body(page):
    raise AssertionError("unsupported frontend archetype: {arch}")
"""


_UNSUPPORTED_MARKER = "unsupported frontend archetype"


def _resolve_body(
    case: PlanCase,
    config: Config,
    llm: object | None,
    dom_context: str,
) -> str:
    """Pick the test body: deterministic archetype vs LLM-generated.

    ``codegen`` policy (config):
      deterministic — archetypes only (ZERO baseline).
      auto          — archetypes first; the LLM covers cases no archetype
                      supports (LLM-proposed plans, unconventional apps).
      llm           — the LLM writes every body (TestSprite-style; needed for
                      apps that don't follow the data-testid convention).
    Any LLM failure falls back to the deterministic result so a run never
    breaks because of the model.
    """
    deterministic = _body(case)
    if llm is None or config.codegen == "deterministic":
        return deterministic
    wants_llm = config.codegen == "llm" or _UNSUPPORTED_MARKER in deterministic
    if not wants_llm:
        return deterministic
    generate = getattr(llm, "generate_frontend_body", None)
    if generate is None:
        return deterministic
    generated = generate(case, dom_context)
    if not generated:
        return deterministic
    return "\n" + generated.rstrip() + "\n"


def export_frontend_tests(
    cases: list[PlanCase],
    summary: CodeSummary,
    config: Config,
    paths: Paths,
    *,
    llm: object | None = None,
    dom_context: str = "",
) -> list[PlanCase]:
    paths.ensure()
    for case in cases:
        header = _HEADER.format(
            base_url=config.base_url,
            username=config.auth.username,
            password=config.auth.password,
            cid=case.id,
        )
        code = header + _resolve_body(case, config, llm, dom_context) + _RUNNER
        filename = f"{case.id}_{case.title}.py"
        paths.test_file(filename).write_text(code, encoding="utf-8")
        case.automation_file = filename
    return cases


__all__ = ["export_frontend_tests"]

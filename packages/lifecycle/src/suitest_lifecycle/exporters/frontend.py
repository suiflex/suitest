"""Render runnable frontend ``TCxxx.py`` files (Playwright async) with recording.

Matches the TestSprite detail view: structured async session (chromium launch
args, ``new_context``, ``set_default_timeout(15000)``), one block per step, a
**video** recorded per test (``record_video_dir``), a per-step trace + final
screenshot written to a ``<TC>.result.json`` sidecar. Each file is standalone;
Suitest provides the browser (user installs nothing).
"""

from __future__ import annotations

from suitest_lifecycle.config import Config
from suitest_lifecycle.models import CodeSummary, PlanCase
from suitest_lifecycle.paths import Paths

_HEADER = '''import asyncio
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


def _ok():
    STEPS.append(dict(_cur, status="PASSED"))


async def _login(page):
    # Authenticate through the real login form.
    _begin("action", "Navigate to /login")
    await page.goto(f"{{BASE_URL}}/login")
    _ok()
    _begin("action", f"Fill '{{USERNAME}}' into the email field")
    await page.get_by_test_id("login-email-input").fill(USERNAME)
    _ok()
    _begin("action", "Fill the password field")
    await page.get_by_test_id("login-password-input").fill(PASSWORD)
    _ok()
    _begin("action", "Click 'Sign in'")
    await page.get_by_test_id("login-submit-button").click()
    _ok()
    _begin("assertion", "Dashboard is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''

_RUNNER = '''

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
        try:
            await page.screenshot(path=screenshot)
        except Exception:
            pass
    except Exception as exc:  # record the failing step + capture a screenshot
        status = "FAILED"
        error = str(exc)
        STEPS.append(dict(_cur, status="FAILED"))
        if page is not None:
            try:
                await page.screenshot(path=screenshot)
            except Exception:
                pass
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
'''


def _body(case: PlanCase) -> str:
    arch = case.source_ref.split(" ", 1)[0].replace("fe:", "")
    route = case.source_ref.split(" ", 1)[1] if " " in case.source_ref else "/"

    if arch == "login_success":
        return '''
async def _body(page):
    await _login(page)
    _begin("assertion", "Dashboard summary is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''
    if arch == "invalid_login":
        return '''
async def _body(page):
    _begin("action", "Navigate to /login")
    await page.goto(f"{BASE_URL}/login")
    _ok()
    _begin("action", "Fill an invalid password")
    await page.get_by_test_id("login-email-input").fill(USERNAME)
    await page.get_by_test_id("login-password-input").fill("wrong-password-xyz")
    _ok()
    _begin("action", "Click 'Sign in'")
    await page.get_by_test_id("login-submit-button").click()
    _ok()
    _begin("assertion", "An error message is shown and the URL stays /login")
    await expect(page.get_by_test_id("login-error-message")).to_be_visible(timeout=TIMEOUT)
    assert "/login" in page.url
    _ok()
'''
    if arch == "protected_redirect":
        return f'''
async def _body(page):
    _begin("action", "Navigate directly to {route} with no session")
    await page.goto(f"{{BASE_URL}}{route}")
    _ok()
    _begin("assertion", "Login page is shown")
    await expect(page.get_by_test_id("login-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''
    if arch == "dashboard_loads":
        return '''
async def _body(page):
    await _login(page)
    _begin("assertion", "Dashboard summary is visible")
    await expect(page.get_by_test_id("dashboard-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''
    if arch == "products_list":
        return '''
async def _body(page):
    await _login(page)
    _begin("action", "Open /products")
    await page.goto(f"{BASE_URL}/products")
    _ok()
    _begin("assertion", "Products page is visible")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''
    if arch == "search_empty":
        return '''
async def _body(page):
    await _login(page)
    _begin("action", "Open /products")
    await page.goto(f"{BASE_URL}/products")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
    _begin("action", "Type an unlikely search query")
    await page.get_by_test_id("product-search-input").fill("zzz-no-such-" + uuid.uuid4().hex[:6])
    await page.wait_for_timeout(600)
    _ok()
    _begin("assertion", "No matching rows are shown")
    assert await page.get_by_test_id("product-row").count() == 0
    _ok()
'''
    if arch == "create_product":
        return '''
async def _body(page):
    await _login(page)
    _begin("action", "Open the product create form")
    await page.goto(f"{BASE_URL}/products/new")
    await expect(page.get_by_test_id("product-form-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
    token = uuid.uuid4().hex[:8]
    _begin("action", "Fill the required product fields")
    await page.get_by_test_id("product-name-input").fill(f"Sutest Product {token}")
    await page.get_by_test_id("product-sku-input").fill(f"SKU-{token}")
    await page.get_by_test_id("product-price-input").fill("19.99")
    await page.get_by_test_id("product-stock-input").fill("5")
    _ok()
    _begin("action", "Submit the form")
    await page.get_by_test_id("product-submit-button").click()
    _ok()
    _begin("assertion", "Returns to the products list")
    await expect(page.get_by_test_id("products-page")).to_be_visible(timeout=TIMEOUT)
    _ok()
'''
    return f'''
async def _body(page):
    raise AssertionError("unsupported frontend archetype: {arch}")
'''


def export_frontend_tests(
    cases: list[PlanCase], summary: CodeSummary, config: Config, paths: Paths
) -> list[PlanCase]:
    paths.ensure()
    for case in cases:
        header = _HEADER.format(
            base_url=config.base_url,
            username=config.auth.username,
            password=config.auth.password,
            cid=case.id,
        )
        code = header + _body(case) + _RUNNER
        filename = f"{case.id}_{case.title}.py"
        paths.test_file(filename).write_text(code, encoding="utf-8")
        case.automation_file = filename
    return cases


__all__ = ["export_frontend_tests"]

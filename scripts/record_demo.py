"""Record the 30-second launch demo against a live `make demo` stack.

Drives the real web UI with Playwright (chromium, 1280×800) and captures a
video: title card → login → Test Cases (Brewly suite, AI badges) → case detail
→ suite run → run detail landing green. Convert the .webm with ffmpeg:

    ffmpeg -i assets/raw/<video>.webm -vf "fps=12,scale=960:-1" assets/demo.gif
    ffmpeg -i assets/raw/<video>.webm -c:v libx264 -pix_fmt yuv420p assets/demo.mp4

Usage:
    uv run --with playwright python scripts/record_demo.py [out_dir]
    (requires `playwright install chromium` once, and `make demo` up)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

WEB = "http://localhost:3000"
EMAIL, PASSWORD = "demo@suitest.dev", "demo1234"

TITLE_CARD = """
<!doctype html><html><head><style>
  body { background:#0a0a0a; margin:0; display:flex; align-items:center;
         justify-content:center; height:100vh;
         font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .wrap { text-align:left; }
  .cmd { color:#fafafa; font-size:34px; }
  .cmd .p { color:#4ade80; }
  .sub { color:#737373; font-size:17px; margin-top:18px;
         font-family: ui-sans-serif, system-ui, sans-serif; }
</style></head><body><div class="wrap">
  <div class="cmd"><span class="p">$</span> make demo</div>
  <div class="sub">PRD → test suite → green run. Open source. Your LLM.</div>
</div></body></html>
"""


async def _pause(page: Page, seconds: float) -> None:
    await page.wait_for_timeout(int(seconds * 1000))


async def _trigger_suite_run(page: Page) -> str:
    """Run the whole Brewly suite through the API using the UI session cookie."""
    req = page.context.request
    workspaces = await (await req.get(f"{WEB}/api/v1/workspaces")).json()
    ws_id = next(w["id"] for w in workspaces if w["slug"] == "demo")
    headers = {"X-Workspace-Id": ws_id}
    projects = await (await req.get(f"{WEB}/api/v1/projects", headers=headers)).json()
    project_items = projects["items"] if isinstance(projects, dict) else projects
    project_id = next(p["id"] for p in project_items if p["slug"] == "brewly")
    suites = await (
        await req.get(
            f"{WEB}/api/v1/suites", headers=headers, params={"projectId": project_id}
        )
    ).json()
    suite_id = next(s["id"] for s in suites if s["name"].startswith("Brewly"))
    run = await (
        await req.post(
            f"{WEB}/api/v1/suites/{suite_id}/run",
            headers=headers,
            data={"name": "Launch demo run"},
        )
    ).json()
    run_id: str = run["id"]
    return run_id


async def main(out_dir: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=out_dir,
            record_video_size={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()

        # 1. Title card
        await page.set_content(TITLE_CARD)
        await _pause(page, 2.5)

        # 2. Login
        await page.goto(f"{WEB}/login")
        await _pause(page, 0.8)
        await page.type("#email", EMAIL, delay=35)
        await page.type("#password", PASSWORD, delay=35)
        await _pause(page, 0.4)
        await page.click("button[type=submit]")
        await page.wait_for_url("**/dashboard**", timeout=15000)
        await _pause(page, 1.5)

        # 3. Test cases — Brewly suite, 5 AI-generated cases
        await page.goto(f"{WEB}/cases")
        await page.wait_for_selector("[data-testid=cases-tree]", timeout=15000)
        await _pause(page, 2.5)

        # 4. Open one generated case (steps + Run now visible)
        await page.click("text=Menu lists all launch items")
        await page.wait_for_selector("[data-testid=case-run-now]", timeout=15000)
        await _pause(page, 2.2)

        # 5. Run the whole suite, watch the run land green
        run_id = await _trigger_suite_run(page)
        await page.goto(f"{WEB}/runs/{run_id}")
        for _ in range(45):
            await _pause(page, 1.0)
            content = await page.content()
            if "Pass" in content and "15 / 15" in content:
                break
        # The header polls but the step list doesn't live-refresh yet — reload
        # once so the recording ends on the fully green step list.
        await page.reload()
        await _pause(page, 4.5)

        await ctx.close()  # flushes the video
        await browser.close()
    print(f"video written under {out_dir}/")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else str(Path("assets/raw"))))

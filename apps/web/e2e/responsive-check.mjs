// Responsive smoke for the Test Runs page against a live `make demo` stack.
// Logs in, opens /runs (with a run selected), then for each viewport asserts
// there is NO page-level horizontal overflow and captures a screenshot.
//
// Usage: node e2e/responsive-check.mjs [outDir=../../assets/raw/responsive]
import { chromium } from "@playwright/test";

const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const EMAIL = "demo@suitest.dev";
const PASSWORD = "demo1234";

const VIEWPORTS = [
  [1920, 1080],
  [1440, 900],
  [1366, 768],
  [1280, 800],
  [1024, 768],
  [768, 1024],
  [390, 844],
];

const outDir = process.argv[2] ?? "../../assets/raw/responsive";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

await page.goto(`${WEB}/login`);
await page.fill("#email", EMAIL);
await page.fill("#password", PASSWORD);
await page.click("button[type=submit]");
await page.waitForURL("**/dashboard**", { timeout: 20000 });

await page.goto(`${WEB}/runs`);
await page.waitForSelector("[data-testid=runs-summary]", { timeout: 20000 });
// Select the first run so the detail panel (steps + evidence tabs) renders.
const row = page.locator("[data-testid=runs-row]").first();
if (await row.count()) {
  await row.click();
  await page.waitForSelector("[data-testid=run-detail]", { timeout: 20000 });
}

let failed = 0;
for (const [w, h] of VIEWPORTS) {
  await page.setViewportSize({ width: w, height: h });
  await page.waitForTimeout(600);
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    const spill = Math.max(doc.scrollWidth - doc.clientWidth, document.body.scrollWidth - doc.clientWidth);
    return { spill, scrollW: doc.scrollWidth, clientW: doc.clientWidth };
  });
  const ok = overflow.spill <= 1; // 1px tolerance for subpixel rounding
  if (!ok) failed += 1;
  console.log(
    `${w}x${h}: ${ok ? "OK" : "FAIL"} (scrollWidth=${overflow.scrollW}, clientWidth=${overflow.clientW}, spill=${overflow.spill}px)`,
  );
  await page.screenshot({ path: `${outDir}/runs-${w}x${h}.png`, fullPage: false });
}

await browser.close();
if (failed > 0) {
  console.error(`${failed} viewport(s) have page-level horizontal overflow`);
  process.exit(1);
}
console.log("All viewports pass — no page-level horizontal overflow.");

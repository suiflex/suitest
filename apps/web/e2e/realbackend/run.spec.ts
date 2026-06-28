import { expect, test } from "@playwright/test";

/**
 * ZERO "Run now" + results — REAL backend, REAL browser, NO mocks (journey
 * steps 6–7). Drives the live stack (api + `make dev-runner` + Redis +
 * `npx @playwright/mcp`) entirely through the UI: switch to the pre-seeded
 * runnable workspace, open its saucedemo case, click "Run now", and watch the
 * run stream to PASS on the run-detail page.
 *
 * The runnable case (one `browser_navigate https://www.saucedemo.com` step on
 * `playwright-mcp`) is seeded by `apps/api/scripts/seed_zero_e2e.py` into the
 * `e2e-run` workspace, kept separate from the EMPTY `e2e-zero` workspace the
 * bootstrap spec starts from.
 */
const E2E_EMAIL = "e2e-zero@suitest.local";
const E2E_PASSWORD = "dogfood-zero-pw-1";

test.describe("ZERO Run now → PASS (real backend, real browser)", () => {
  // The runner's FIRST playwright-mcp spawn is cold — it npx-resolves the
  // package and launches a browser before the navigate even starts — so the run
  // can take well over a minute. Give the whole journey generous room.
  test.setTimeout(300_000);

  test("runs a saucedemo case and streams to PASS from the UI", async ({ page }) => {
    await page.goto("/login?next=/dashboard");
    await page.fill("#email", E2E_EMAIL);
    await page.fill("#password", E2E_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("app-shell")).toBeVisible();

    // Switch to the pre-seeded runnable workspace via the sidebar picker.
    await page.getByTestId("workspace-picker").click();
    await page
      .getByTestId("workspace-picker-list")
      .getByTestId("workspace-picker-item")
      .filter({ hasText: "E2E Run" })
      .click();
    await page.waitForURL("**/dashboard");

    // Open the seeded (passing) saucedemo case by name — the workspace also
    // holds a deliberately-failing case used by defect.spec.
    await page.goto("/cases");
    await expect(page.getByTestId("cases-screen")).toBeVisible();
    await page.getByTestId("cases-tree-row").filter({ hasText: "Open saucedemo" }).click();
    await expect(page.getByTestId("case-detail")).toBeVisible();

    // Run now → land on the run-detail page.
    await page.getByTestId("case-run-now").click();
    await page.waitForURL(/\/runs\//);
    await expect(page.getByTestId("run-detail-page")).toBeVisible();

    // The run streams (WS) to a terminal PASS — a real browser navigated to
    // saucedemo via playwright-mcp.
    await expect(page.getByTestId("run-summary-card").getByTestId("status-badge")).toHaveAttribute(
      "data-status",
      "pass",
      { timeout: 260_000 },
    );

    // Journey step 8: the run shows up on the analytics dashboard.
    await page.goto("/dashboard");
    await expect(page.getByTestId("dashboard-screen")).toBeVisible();
    await expect(page.getByTestId("dashboard-pass-rate")).toBeVisible();
    await expect(page.getByTestId("recent-run-row").first()).toBeVisible();
  });
});

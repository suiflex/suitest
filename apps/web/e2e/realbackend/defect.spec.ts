import { expect, test } from "@playwright/test";

/**
 * ZERO "make it fail → triage → defect" (journey step 10) — REAL backend, REAL
 * browser, NO mocks. Runs the deliberately-broken case (a `browser_navigate` to
 * a dead endpoint → step FAIL) through the UI; the runner auto-files a defect,
 * which the test then sees on the Defects screen.
 *
 * The failing case is seeded into the `e2e-run` workspace alongside the passing
 * one by `apps/api/scripts/seed_zero_e2e.py`.
 */
const E2E_EMAIL = "e2e-zero@suitest.local";
const E2E_PASSWORD = "dogfood-zero-pw-1";

test.describe("ZERO failing run → auto-filed defect (real backend)", () => {
  test.setTimeout(300_000);

  test("a failing case files a defect visible on the Defects screen", async ({ page }) => {
    await page.goto("/login?next=/dashboard");
    await page.fill("#email", E2E_EMAIL);
    await page.fill("#password", E2E_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("app-shell")).toBeVisible();

    await page.getByTestId("workspace-picker").click();
    await page
      .getByTestId("workspace-picker-list")
      .getByTestId("workspace-picker-item")
      .filter({ hasText: "E2E Run" })
      .click();
    await page.waitForURL("**/dashboard");

    await page.goto("/cases");
    await expect(page.getByTestId("cases-screen")).toBeVisible();
    await page.getByTestId("cases-tree-row").filter({ hasText: "Broken checkout" }).click();
    await expect(page.getByTestId("case-detail")).toBeVisible();

    await page.getByTestId("case-run-now").click();
    await page.waitForURL(/\/runs\//);
    await expect(
      page.getByTestId("run-summary-card").getByTestId("status-badge"),
    ).toHaveAttribute("data-status", "fail", { timeout: 260_000 });

    // The failure auto-filed a defect — it shows on the Defects screen, where a
    // ZERO user triages it (manual triage; no LLM).
    await page.goto("/defects");
    await expect(page.getByTestId("defect-card").first()).toBeVisible({ timeout: 30_000 });
  });
});

import { expect, test } from "@playwright/test";

/**
 * ZERO "mark a suite as gating" (journey step 9) — REAL backend, NO mocks.
 * Deterministic + LLM-free; no run required. Drives the seeded `e2e-run`
 * workspace's Cases screen, marks its suite as the gating suite, and asserts the
 * Gating badge appears (`PATCH /projects/:id { gatingSuiteId }`).
 */
const E2E_EMAIL = "e2e-zero@suitest.local";
const E2E_PASSWORD = "dogfood-zero-pw-1";

test.describe("ZERO mark suite gating (real backend)", () => {
  test("marks the suite as the gating suite from the UI", async ({ page }) => {
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

    await page.getByTestId("suite-set-gating-btn").first().click();
    await expect(page.getByTestId("suite-gating-badge")).toBeVisible({ timeout: 15_000 });
  });
});

import { expect, test } from "@playwright/test";

/**
 * ZERO dogfood bootstrap — REAL backend, NO mocks.
 *
 * Proves that a brand-new ZERO install (one user + one empty workspace, seeded
 * by `apps/api/scripts/seed_zero_e2e.py`) can create its first project and suite
 * entirely from the web UI — the journey-step-2 blocker the dogfood loop exists
 * to close (`docs/loops/ZERO_READINESS_DOGFOOD_LOOP.md`). Every request hits the
 * live FastAPI backend through the Vite proxy; no `/api` interception.
 *
 * Mirrors the seed fixture credentials.
 */
const E2E_EMAIL = "e2e-zero@suitest.local";
const E2E_PASSWORD = "dogfood-zero-pw-1";

test.describe("ZERO dogfood bootstrap (real backend)", () => {
  test("an empty install creates its first project + suite from the UI", async ({ page }) => {
    // 1. Log in with the seeded ZERO user via the password form (no OAuth).
    await page.goto("/login?next=/cases");
    await page.fill("#email", E2E_EMAIL);
    await page.fill("#password", E2E_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    // 2. Land on Cases. The seeded workspace has no projects → first-project
    //    bootstrap empty state.
    await expect(page.getByTestId("cases-screen")).toBeVisible();
    await expect(page.getByText("Create your first project")).toBeVisible();

    // 3. Create the first project entirely from the UI.
    await page.getByRole("button", { name: "New project" }).click();
    await expect(page.getByTestId("create-project-dialog")).toBeVisible();
    await page.getByTestId("create-project-name").fill("Swag Labs");
    await page.getByTestId("create-project-submit").click();

    // 4. With a project but no suites → first-suite bootstrap empty state.
    await expect(page.getByText("Create your first suite")).toBeVisible();

    // 5. Create the first suite entirely from the UI.
    await page.getByRole("button", { name: "New suite" }).click();
    await expect(page.getByTestId("create-suite-dialog")).toBeVisible();
    await page.getByTestId("create-suite-name").fill("Login flow");
    await page.getByTestId("create-suite-submit").click();

    // 6. The suite now exists: the Cases tree layout renders (the persistent
    //    "New suite" button only appears when ≥1 suite exists) over an empty
    //    "No cases yet" state — a brand-new empty Suitest now has its first suite.
    await expect(page.getByTestId("new-suite-btn")).toBeVisible();
    await expect(page.getByText("No cases yet")).toBeVisible();
  });
});

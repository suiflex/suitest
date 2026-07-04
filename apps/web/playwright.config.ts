import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the M1b DoD smoke E2E.
 *
 * Boots the Vite dev server on http://localhost:3000 (reused locally if
 * already running) and intercepts every `/api/v1/**` + `/capabilities`
 * request inside the spec — see `e2e/m1b-smoke.spec.ts`. The smoke test is
 * therefore self-contained and does NOT require the M1a backend to be
 * running, which keeps CI portable.
 *
 * Traces are retained on failure for triage; on green runs they're tossed.
 */
export default defineConfig({
  testDir: "./e2e",
  // The real-backend dogfood specs need a LIVE api+web stack (see
  // `playwright.realbackend.config.ts`); never run them under this mocked config.
  testIgnore: "realbackend/**",
  fullyParallel: false,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 1 : 0,
  reporter: process.env["CI"] ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  // Single pinned project so `--project=chromium` (used by the m1d-e2e
  // workflow) resolves, and visual-regression baselines render on one engine.
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm --filter @suiflex/web dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env["CI"],
    timeout: 60_000,
  },
});

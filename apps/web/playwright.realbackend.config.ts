import { defineConfig, devices } from "@playwright/test";

/**
 * Real-backend (NO-MOCK) Playwright config — the dogfood harness.
 *
 * Unlike `playwright.config.ts` (which intercepts every `/api/v1/**` from
 * fixtures), this config drives the UI against a LIVE stack:
 *
 *   UI (vite :3000)  ──proxy /api,/auth,/capabilities──▶  FastAPI (:4000)  ──▶  Postgres
 *
 * so the FE↔BE seam — where the bootstrap bugs live — is actually exercised.
 * The api boots at ZERO tier (LLM env stripped by `make dev-api-zero`); the
 * seeded workspace also carries a ZERO `WorkspaceCapability`, so no LLM is
 * involved anywhere in the journey.
 *
 * Prereq: a seeded ZERO state (one user + one empty workspace). `make e2e-real`
 * runs `apps/api/scripts/seed_zero_e2e.py` before invoking this config.
 *
 * Specs live in `./e2e/realbackend` (the mocked `./e2e` suite is excluded from
 * this run via `testDir`; the default config excludes `realbackend/**`).
 */
export default defineConfig({
  testDir: "./e2e/realbackend",
  fullyParallel: false,
  forbidOnly: !!process.env["CI"],
  retries: 0,
  reporter: process.env["CI"] ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // ZERO-tier api (LLM env stripped). `cwd` points make at the repo root so
      // it auto-loads `.env` for the DB/Redis connection.
      command: "make dev-api-zero",
      cwd: "../..",
      url: "http://localhost:4000/capabilities/health",
      reuseExistingServer: !process.env["CI"],
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "pnpm dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env["CI"],
      timeout: 60_000,
    },
  ],
});

/**
 * M1d-31 visual-regression E2E spec.
 *
 * Approach: backend-agnostic, same interception pattern as m1b-smoke.spec.ts.
 * Every /capabilities and /api/v1/** GET is intercepted by page.route() and
 * answered from inline fixtures. The Vite dev server runs on :3000.
 *
 * IMPORTANT — baselines are generated in CI via:
 *   playwright test visual-regression.spec.ts --update-snapshots
 * Baseline PNGs are NOT committed from a local sandbox because font rendering
 * and sub-pixel antialiasing differ per platform/OS. The CI runner is the
 * canonical source of truth for snapshots.
 *
 * Snapshot directories (apps/web/e2e/**-snapshots/) are gitignored.
 */
import { test, expect, type Route } from "@playwright/test";

import capabilitiesZero from "../src/mocks/fixtures/capabilities-zero.json" with { type: "json" };
import cases from "../src/mocks/fixtures/cases.json" with { type: "json" };
import coverage from "../src/mocks/fixtures/coverage.json" with { type: "json" };
import defects from "../src/mocks/fixtures/defects.json" with { type: "json" };
import docs from "../src/mocks/fixtures/docs.json" with { type: "json" };
import flaky from "../src/mocks/fixtures/flaky.json" with { type: "json" };
import heatmap from "../src/mocks/fixtures/heatmap.json" with { type: "json" };
import inbox from "../src/mocks/fixtures/inbox.json" with { type: "json" };
import integrations from "../src/mocks/fixtures/integrations.json" with { type: "json" };
import kpis from "../src/mocks/fixtures/kpis.json" with { type: "json" };
import mcpProviders from "../src/mocks/fixtures/mcp-providers.json" with { type: "json" };
import passRate from "../src/mocks/fixtures/pass-rate.json" with { type: "json" };
import readiness from "../src/mocks/fixtures/readiness.json" with { type: "json" };
import runs from "../src/mocks/fixtures/runs.json" with { type: "json" };
import suites from "../src/mocks/fixtures/suites.json" with { type: "json" };
import traceability from "../src/mocks/fixtures/traceability.json" with { type: "json" };

const ME = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  email: "maya@nusantararetail.local",
  name: "Maya Putri",
  avatar_url: null,
  memberships: [
    {
      workspace_id: "ws_1",
      role: "OWNER",
      workspace: { id: "ws_1", slug: "nusantara-retail", name: "Nusantara Retail" },
    },
  ],
};

const RUNS_SUMMARY = {
  activeNow: 1,
  today: 24,
  passed: 22,
  failed: 2,
  avgDurationMs: 84000,
  queue: 3,
};

const EMPTY_PAGE = { items: [], meta: { nextCursor: null, limit: 20 } };
const EMPTY_ITEMS = { items: [] };

function fulfillJson(route: Route, body: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

type RouteHandler = (route: Route) => Promise<void>;

/**
 * Route table mirrors m1b-smoke.spec.ts: specific paths first, generic prefix last.
 * Specific routes must come BEFORE their generic prefix (e.g. /runs/summary before /runs/).
 */
const ROUTE_TABLE: Array<{ match: (url: string) => boolean; handler: RouteHandler }> = [
  { match: (u) => /\/capabilities(\?|$)/.test(u), handler: (r) => fulfillJson(r, capabilitiesZero) },

  // Auth
  { match: (u) => u.includes("/api/v1/auth/me"), handler: (r) => fulfillJson(r, ME) },

  // Analytics
  { match: (u) => u.includes("/api/v1/analytics/kpis"), handler: (r) => fulfillJson(r, kpis) },
  { match: (u) => u.includes("/api/v1/analytics/pass-rate"), handler: (r) => fulfillJson(r, passRate) },
  { match: (u) => u.includes("/api/v1/analytics/coverage"), handler: (r) => fulfillJson(r, coverage) },
  { match: (u) => u.includes("/api/v1/analytics/flaky"), handler: (r) => fulfillJson(r, flaky) },
  { match: (u) => u.includes("/api/v1/analytics/heatmap"), handler: (r) => fulfillJson(r, heatmap) },
  { match: (u) => u.includes("/api/v1/analytics/readiness"), handler: (r) => fulfillJson(r, readiness) },

  // Runs — order matters: /runs/summary before /runs/:id and /runs.
  { match: (u) => u.includes("/api/v1/runs/summary"), handler: (r) => fulfillJson(r, RUNS_SUMMARY) },
  { match: (u) => /\/api\/v1\/runs\/[^/]+\/steps/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
  { match: (u) => /\/api\/v1\/runs\/[^/]+\/logs/.test(u), handler: (r) => fulfillJson(r, { lines: [], nextCursor: null }) },
  { match: (u) => /\/api\/v1\/runs\/[^/]+\/artifacts/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
  { match: (u) => /\/api\/v1\/runs\/[^/]+\/network/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
  { match: (u) => u.includes("/api/v1/runs"), handler: (r) => fulfillJson(r, runs) },

  // TCM
  { match: (u) => u.includes("/api/v1/test-cases"), handler: (r) => fulfillJson(r, cases) },
  { match: (u) => u.includes("/api/v1/suites"), handler: (r) => fulfillJson(r, suites) },

  // Other resources
  { match: (u) => u.includes("/api/v1/defects"), handler: (r) => fulfillJson(r, defects) },
  { match: (u) => u.includes("/api/v1/documents"), handler: (r) => fulfillJson(r, docs) },
  { match: (u) => u.includes("/api/v1/integrations"), handler: (r) => fulfillJson(r, integrations) },
  { match: (u) => u.includes("/api/v1/traceability/matrix"), handler: (r) => fulfillJson(r, traceability) },
  { match: (u) => u.includes("/api/v1/mcp/providers"), handler: (r) => fulfillJson(r, mcpProviders) },
  { match: (u) => u.includes("/api/v1/inbox"), handler: (r) => fulfillJson(r, inbox) },
  { match: (u) => u.includes("/api/v1/audit-logs"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
];

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    const isApi = url.includes("/api/v1/") || url.includes("/capabilities");
    if (!isApi) return route.continue();
    if (req.method() !== "GET") return route.continue();

    const entry = ROUTE_TABLE.find((e) => e.match(url));
    if (entry) return entry.handler(route);
    return fulfillJson(route, EMPTY_PAGE);
  });
});

/**
 * Visual regression: Cases edit screen.
 *
 * Navigates to /cases, waits for the "Test Cases" heading to be visible
 * (data has resolved), then takes a full-page screenshot and compares to the
 * stored baseline with a 5% pixel-ratio tolerance.
 */
test("visual-regression: cases screen", async ({ page }) => {
  await page.goto("/cases");
  await expect(
    page.getByRole("heading", { name: "Test Cases", level: 2 }),
  ).toBeVisible({ timeout: 10_000 });

  await expect(page).toHaveScreenshot("cases.png", {
    maxDiffPixelRatio: 0.05,
    fullPage: true,
  });
});

/**
 * Visual regression: Defects screen.
 */
test("visual-regression: defects screen", async ({ page }) => {
  await page.goto("/defects");
  await expect(
    page.getByRole("heading", { name: "Defects", level: 2 }),
  ).toBeVisible({ timeout: 10_000 });

  await expect(page).toHaveScreenshot("defects.png", {
    maxDiffPixelRatio: 0.05,
    fullPage: true,
  });
});

/**
 * Visual regression: Integrations screen.
 */
test("visual-regression: integrations screen", async ({ page }) => {
  await page.goto("/integrations");
  await expect(
    page.getByRole("heading", { name: "Integrations", level: 2 }),
  ).toBeVisible({ timeout: 10_000 });

  await expect(page).toHaveScreenshot("integrations.png", {
    maxDiffPixelRatio: 0.05,
    fullPage: true,
  });
});

/**
 * Visual regression: Dashboard screen.
 */
test("visual-regression: dashboard screen", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Dashboard", level: 2 }),
  ).toBeVisible({ timeout: 10_000 });

  await expect(page).toHaveScreenshot("dashboard.png", {
    maxDiffPixelRatio: 0.05,
    fullPage: true,
  });
});

/**
 * M1b DoD smoke E2E (Task 13).
 *
 * Approach: backend-agnostic. Every `/capabilities` and `/api/v1/**` GET is
 * intercepted by `page.route(...)` and answered from inline fixtures that
 * mirror the MSW handlers in `apps/web/src/mocks/handlers.ts`. This keeps the
 * suite portable for CI — no M1a backend, no seed user, no live cookie needed.
 *
 * Two specs:
 *  1. Navigate every screen in ZERO tier and assert the heading + zero
 *     console errors.
 *  2. Assert the AI panel is hidden and the tier badge reads "ZERO".
 *
 * If a future Task wants a true end-to-end against the real M1a backend +
 * seed (Maya), spin it up at :4000 and replace the `beforeEach` interception
 * with a real `POST /api/v1/auth/cookie/login` — the route paths under test
 * stay identical.
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

/**
 * Map of URL substring → JSON body. Matched in declaration order; first hit
 * wins. Specific routes must come BEFORE their generic prefix (e.g.
 * `/runs/summary` before `/runs/`).
 */
function fulfillJson(route: Route, body: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

type RouteHandler = (route: Route) => Promise<void>;

const ROUTE_TABLE: Array<{ match: (url: string) => boolean; handler: RouteHandler }> = [
  // /capabilities is mounted at the application root, not under /api/v1.
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
  // Catch-all interceptor. GET requests are dispatched through ROUTE_TABLE;
  // anything we haven't mocked falls back to an empty paginated page so the
  // axios client never throws and screens render their empty states cleanly.
  // Non-GET requests pass through (M1b is read-only, so they shouldn't fire).
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

test("M1b smoke: navigate every screen, no console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));

  const screens: ReadonlyArray<{ path: string; heading: string | RegExp }> = [
    { path: "/dashboard", heading: "Dashboard" },
    { path: "/inbox", heading: "Inbox" },
    { path: "/cases", heading: "Test Cases" },
    { path: "/runs", heading: "Test Runs" },
    { path: "/defects", heading: "Defects" },
    { path: "/analytics", heading: "Analytics" },
    { path: "/trace", heading: "Traceability" },
    { path: "/integrations", heading: "Integrations" },
    { path: "/docs", heading: /Docs/i },
  ];

  for (const s of screens) {
    await page.goto(s.path);
    await expect(
      page.getByRole("heading", { name: s.heading, level: 2 }),
    ).toBeVisible({ timeout: 10_000 });
  }

  expect(errors).toEqual([]);
});

test("M1b ZERO: AI panel hidden + tier badge shows ZERO", async ({ page }) => {
  await page.goto("/dashboard");

  // AiPanel is wrapped in <Gated feature="ai_conversation"> and renders null
  // in ZERO. The aside element (and its data-testid) must not be in the DOM.
  await expect(page.locator('[data-testid="ai-panel"]')).toHaveCount(0);

  // Tier badge in the topbar reads "ZERO".
  await expect(page.getByTestId("tier-badge")).toContainText("ZERO");
});

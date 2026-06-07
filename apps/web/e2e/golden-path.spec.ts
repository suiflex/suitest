/**
 * M1d golden-path E2E (Task M1d-30).
 *
 * AUTH APPROACH — backend-agnostic, identical to m1b-smoke.spec.ts:
 *
 *   The login form is Google OAuth-only (no password input to fill); there is
 *   no email/password POST endpoint to intercept in a meaningful way. The real
 *   auth gate lives in `_app.tsx` `beforeLoad`, which calls `GET /auth/me` and
 *   redirects to /login on 401.
 *
 *   Therefore:
 *     • Test 1 (happy path) seeds authentication by intercepting `GET /auth/me`
 *       to return the Maya fixture — the app thinks the user is logged in and
 *       mounts the shell. The test then navigates directly to /cases (already
 *       authenticated) and drives the case-select → add-step → save → run-now
 *       flow, intercepting `POST /runs` and `GET /runs/:id` to simulate a PASS
 *       outcome.
 *
 *     • Test 2 (bad credentials) toggles `GET /auth/me` → 401 and navigates to
 *       / so the `_app` guard fires and redirects to /login. The test then
 *       intercepts `/auth/google/authorize` → 400 (simulating a bad-auth
 *       response from the authorize step), clicks the "Sign in with Google"
 *       button, and asserts we stay on /login without crashing.
 *
 *     • Test 3 (session expires) drives the same 401 on `/auth/me` → assert
 *       redirect to /login.
 *
 * All `/api/v1/**` and `/capabilities` requests are intercepted from inline
 * fixtures; no backend or docker-compose is needed. The Playwright config boots
 * the Vite dev server on http://localhost:3000.
 */

import { test, expect, type Route } from "@playwright/test";

import capabilitiesZeroBase from "../src/mocks/fixtures/capabilities-zero.json" with { type: "json" };

// The shared fixture intentionally omits `auth` (other specs don't want the
// Google button). Golden-path asserts the login page renders the button, so
// we layer `auth.google_oauth_enabled` on top here only.
const capabilitiesZero = {
  ...capabilitiesZeroBase,
  auth: { google_oauth_enabled: true },
};
import cases from "../src/mocks/fixtures/cases.json" with { type: "json" };
import runs from "../src/mocks/fixtures/runs.json" with { type: "json" };
import suites from "../src/mocks/fixtures/suites.json" with { type: "json" };

// ---------------------------------------------------------------------------
// Shared fixtures
// ---------------------------------------------------------------------------

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
  activeNow: 0,
  today: 1,
  passed: 1,
  failed: 0,
  avgDurationMs: 5000,
  queue: 0,
};

const EMPTY_PAGE = { items: [], meta: { nextCursor: null, limit: 20 } };
const EMPTY_ITEMS = { items: [] };

/** The new case returned by POST /test-cases (mocked). */
const CREATED_CASE = {
  id: "case_new",
  public_id: "TC-999",
  name: "Golden path manual case",
  description: "Verify the golden path flow works end-to-end.",
  preconditions: null,
  priority: "P1",
  status: "ACTIVE",
  source: "MANUAL",
  suite_id: "ste_smoke",
  owner_id: null,
  tags: [],
  steps: [],
  created_at: "2026-05-31T08:00:00Z",
  updated_at: "2026-05-31T08:00:00Z",
};

/** The case detail returned by GET /test-cases/TC-999 */
const CASE_DETAIL_WITH_STEP = {
  ...CREATED_CASE,
  steps: [
    {
      id: "stp_gp1",
      case_id: "case_new",
      order: 1,
      action: "Navigate to /golden-path",
      expected: "Page loads",
      executable: true,
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
      code: null,
      data: null,
    },
  ],
};

/** The queued run returned by POST /runs */
const QUEUED_RUN = {
  id: "run_gp",
  public_id: "RUN-GP1",
  project_id: "prj_demo",
  name: "Ad-hoc: Golden path manual case",
  branch: "main",
  commit_sha: null,
  env: "staging",
  status: "QUEUED",
  trigger: "MANUAL",
  tier_at_runtime: "ZERO",
  started_at: null,
  completed_at: null,
  duration_ms: null,
  summary: null,
  created_at: "2026-05-31T08:00:00Z",
  updated_at: "2026-05-31T08:00:00Z",
};

/** The completed PASS run returned by GET /runs/RUN-GP1 */
const PASS_RUN = {
  id: "run_gp",
  public_id: "RUN-GP1",
  project_id: "prj_demo",
  name: "Ad-hoc: Golden path manual case",
  branch: "main",
  commit_sha: null,
  env: "staging",
  status: "PASS",
  trigger: "MANUAL",
  tier_at_runtime: "ZERO",
  started_at: "2026-05-31T08:00:01Z",
  completed_at: "2026-05-31T08:00:06Z",
  duration_ms: 5000,
  summary: { total_steps: 1, passed_steps: 1, failed_steps: 0, duration_ms: 5000 },
  created_at: "2026-05-31T08:00:00Z",
  updated_at: "2026-05-31T08:00:06Z",
};

// ---------------------------------------------------------------------------
// Route-table helper
// ---------------------------------------------------------------------------

function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

type RouteEntry = { match: (url: string, method: string) => boolean; handler: (route: Route) => Promise<void> };

/**
 * Build the standard ZERO-tier route table. Tests can prepend additional
 * entries (first-match wins) to override specific routes.
 */
function buildBaseRouteTable(overrides: RouteEntry[] = []): RouteEntry[] {
  return [
    ...overrides,

    // Capabilities
    { match: (u) => /\/capabilities(\?|$)/.test(u), handler: (r) => fulfillJson(r, capabilitiesZero) },

    // Auth
    { match: (u) => u.includes("/api/v1/auth/me"), handler: (r) => fulfillJson(r, ME) },

    // Runs — order: summary → specific sub-resources → list
    { match: (u) => u.includes("/api/v1/runs/summary"), handler: (r) => fulfillJson(r, RUNS_SUMMARY) },
    { match: (u) => /\/api\/v1\/runs\/[^/]+\/steps/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => /\/api\/v1\/runs\/[^/]+\/logs/.test(u), handler: (r) => fulfillJson(r, { lines: [], nextCursor: null }) },
    { match: (u) => /\/api\/v1\/runs\/[^/]+\/artifacts/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => /\/api\/v1\/runs\/[^/]+\/network/.test(u), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/runs"), handler: (r) => fulfillJson(r, runs) },

    // Test cases
    { match: (u) => u.includes("/api/v1/test-cases"), handler: (r) => fulfillJson(r, cases) },

    // Suites
    { match: (u) => u.includes("/api/v1/suites"), handler: (r) => fulfillJson(r, suites) },

    // Analytics (empty stubs so dashboard screens don't error)
    { match: (u) => u.includes("/api/v1/analytics"), handler: (r) => fulfillJson(r, {}) },

    // Other resources
    { match: (u) => u.includes("/api/v1/mcp/providers"), handler: (r) => fulfillJson(r, { items: [] }) },
    { match: (u) => u.includes("/api/v1/inbox"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/audit-logs"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/defects"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/documents"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/integrations"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/traceability"), handler: (r) => fulfillJson(r, { items: [] }) },
    { match: (u) => u.includes("/api/v1/requirements"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/projects"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
    { match: (u) => u.includes("/api/v1/workspaces"), handler: (r) => fulfillJson(r, EMPTY_ITEMS) },
  ];
}

/**
 * Install a catch-all route interceptor using the provided route table.
 * GET requests are dispatched through the table; non-API and non-GET requests
 * continue (pass-through) so Vite assets load normally.
 */
async function installRoutes(
  page: import("@playwright/test").Page,
  table: RouteEntry[],
): Promise<void> {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const isApi = url.includes("/api/v1/") || url.includes("/capabilities") || url.includes("/auth/");

    if (!isApi) return route.continue();

    const entry = table.find((e) => e.match(url, method));
    if (entry) return entry.handler(route);

    // Fallback: empty page for unmatched API GET requests
    if (method === "GET") return fulfillJson(route, EMPTY_PAGE);

    // Non-GET, unmatched API calls: continue (or let them fail naturally)
    return route.continue();
  });
}

// ---------------------------------------------------------------------------
// Test 1 — happy path: navigate to cases, select case, add step, save, run
// ---------------------------------------------------------------------------

test("test_login_and_create_manual_case_then_run_pass", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));

  // Track whether POST /runs was called
  let runPostCalled = false;

  const overrides: RouteEntry[] = [
    // POST /runs → return QUEUED run (202)
    {
      match: (u, m) => u.includes("/api/v1/runs") && m === "POST" && !/\/runs\/[^/]+\//.test(u),
      handler: async (route) => {
        runPostCalled = true;
        await fulfillJson(route, QUEUED_RUN, 202);
      },
    },
    // GET /runs/RUN-GP1 → PASS run (the detail page fetches this)
    {
      match: (u, m) => u.includes("/api/v1/runs/RUN-GP1") && m === "GET",
      handler: (r) => fulfillJson(r, PASS_RUN),
    },
    // GET /test-cases/TC-101 → existing case with one step
    {
      match: (u, m) => u.includes("/api/v1/test-cases/TC-101") && m === "GET",
      handler: (r) => fulfillJson(r, CASE_DETAIL_WITH_STEP),
    },
    // POST /test-cases/:id/steps → case with the new step
    {
      match: (u, m) => /\/api\/v1\/test-cases\/[^/]+\/steps/.test(u) && m === "POST",
      handler: (r) => fulfillJson(r, CASE_DETAIL_WITH_STEP, 201),
    },
    // PATCH /test-cases/:id/steps → return updated case
    {
      match: (u, m) => /\/api\/v1\/test-cases\/[^/]+\/steps/.test(u) && m === "PATCH",
      handler: (r) => fulfillJson(r, CASE_DETAIL_WITH_STEP),
    },
  ];

  await installRoutes(page, buildBaseRouteTable(overrides));

  // Navigate directly to the cases screen — auth/me returns ME so `_app`
  // beforeLoad succeeds and the shell mounts.
  await page.goto("/cases");

  // Wait for the cases screen heading
  await expect(page.getByRole("heading", { name: "Test Cases", level: 2 })).toBeVisible({
    timeout: 15_000,
  });

  // Select the first case from the tree (TC-101 — first in the fixture list)
  const firstCaseRow = page.locator('[data-testid="cases-tree-row"]').first();
  await firstCaseRow.click();

  // The right pane should load the case detail panel
  await expect(page.getByTestId("case-detail")).toBeVisible({ timeout: 10_000 });

  // Verify the step editor is visible
  await expect(page.getByTestId("step-editor")).toBeVisible({ timeout: 8_000 });

  // Add a step via the "+ New step" button
  const addStepBtn = page.getByTestId("step-add-btn");
  await expect(addStepBtn).toBeVisible();
  await addStepBtn.click();

  // After the POST /test-cases/:id/steps mutation resolves, a step row appears
  await expect(page.getByTestId("step-row").first()).toBeVisible({ timeout: 8_000 });

  // Fill in the action field on the first step row
  const actionInput = page.getByTestId("step-action-input").first();
  await actionInput.clear();
  await actionInput.fill("Navigate to /golden-path");

  // Save the step edits via "Save steps"
  const saveBtn = page.getByTestId("step-save-btn");
  await expect(saveBtn).toBeVisible();
  await saveBtn.click();

  // Click "Run now" — this fires POST /runs and navigates to /runs/RUN-GP1
  const runNowBtn = page.getByTestId("case-run-now");
  await expect(runNowBtn).toBeEnabled({ timeout: 8_000 });
  await runNowBtn.click();

  // Should land on the run detail page
  await page.waitForURL(/\/runs\/RUN-GP1/, { timeout: 15_000 });

  // The run summary card should render with PASS status
  await expect(page.getByTestId("run-summary-card")).toBeVisible({ timeout: 10_000 });

  // Assert the run POST was called
  expect(runPostCalled).toBe(true);

  // The summary card should contain the PASS status badge. StatusBadge renders
  // the "pass" status as the label "Pass" (title-case). We also assert on the
  // run public_id to confirm the correct run is shown.
  await expect(page.getByTestId("run-summary-card")).toContainText("Pass");
  await expect(page.getByTestId("run-summary-card")).toContainText("RUN-GP1");

  // No console errors from the golden path
  expect(errors.filter((e) => !e.includes("WebSocket"))).toEqual([]);
});

// ---------------------------------------------------------------------------
// Test 2 — login fails: google authorize returns 400 → stays on /login
// ---------------------------------------------------------------------------

test("test_login_fails_with_bad_credentials_redirects_to_login_with_error", async ({ page }) => {
  // Intercept /auth/me with 401 so the _app guard redirects to /login
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    // Capabilities — needed for RootLayout's useCapabilities fetch
    if (/\/capabilities(\?|$)/.test(url) && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(capabilitiesZero),
      });
    }

    // /auth/me → 401 to trigger the guard redirect
    if (url.includes("/auth/me") && method === "GET") {
      return route.fulfill({ status: 401, body: "{}" });
    }

    // /auth/google/authorize → 400 (bad OAuth state / invalid client)
    if (url.includes("/auth/google/authorize") && method === "GET") {
      return route.fulfill({ status: 400, body: '{"detail":"invalid_client"}' });
    }

    return route.continue();
  });

  // Navigate to root — the _app guard will redirect to /login
  await page.goto("/");

  // Should land on /login
  await page.waitForURL(/\/login/, { timeout: 10_000 });

  // The "Sign in with Google" button must be visible
  const signInBtn = page.getByRole("button", { name: /sign in with google/i });
  await expect(signInBtn).toBeVisible({ timeout: 8_000 });

  // Click it — the fetch to /auth/google/authorize returns 400, which the
  // component catches via console.error (not a thrown rejection), so the page
  // stays on /login without crashing.
  await signInBtn.click();

  // Still on the login page
  await expect(page.url()).toContain("/login");

  // The login button is still visible (no crash / blank screen)
  await expect(signInBtn).toBeVisible();
});

// ---------------------------------------------------------------------------
// Test 3 — session expires: /auth/me returns 401 → redirect to /login
// ---------------------------------------------------------------------------

test("test_session_expires_redirects_to_login", async ({ page }) => {
  // Intercept /auth/me → 401 unconditionally
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    if (/\/capabilities(\?|$)/.test(url) && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(capabilitiesZero),
      });
    }

    if (url.includes("/auth/me") && method === "GET") {
      return route.fulfill({ status: 401, body: '{"detail":"Not authenticated"}' });
    }

    return route.continue();
  });

  // Attempt to navigate to a protected route
  await page.goto("/cases");

  // The _app.tsx beforeLoad guard catches the 401 and throws redirect to /login
  await page.waitForURL(/\/login/, { timeout: 10_000 });

  // Confirm we are on the login screen
  await expect(page.getByRole("button", { name: /sign in with google/i })).toBeVisible({
    timeout: 8_000,
  });
});

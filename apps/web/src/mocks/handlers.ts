import { http, HttpResponse, type HttpHandler } from "msw";

import capabilitiesZero from "./fixtures/capabilities-zero.json";
import cases from "./fixtures/cases.json";
import coverage from "./fixtures/coverage.json";
import defects from "./fixtures/defects.json";
import docs from "./fixtures/docs.json";
import flaky from "./fixtures/flaky.json";
import heatmap from "./fixtures/heatmap.json";
import inbox from "./fixtures/inbox.json";
import integrations from "./fixtures/integrations.json";
import kpis from "./fixtures/kpis.json";
import passRate from "./fixtures/pass-rate.json";
import readiness from "./fixtures/readiness.json";
import runs from "./fixtures/runs.json";
import suites from "./fixtures/suites.json";
import traceability from "./fixtures/traceability.json";

// Base URL the axios client uses. Keep handlers thin — per-screen tests
// override via `server.use(...)`.
// Use a wildcard origin so the same handlers match regardless of whether the
// caller uses a relative `/api/v1/...` path (browser) or an absolute test URL
// (Vitest http adapter).
const BASE = "*/api/v1";

export const handlers: HttpHandler[] = [
  // Capabilities (mounted at root, not /api/v1)
  http.get("*/capabilities", () => HttpResponse.json(capabilitiesZero)),
  http.get(`${BASE}/capabilities`, () => HttpResponse.json(capabilitiesZero)),

  // Analytics
  http.get(`${BASE}/analytics/kpis`, () => HttpResponse.json(kpis)),
  http.get(`${BASE}/analytics/pass-rate`, () => HttpResponse.json(passRate)),
  http.get(`${BASE}/analytics/coverage`, () => HttpResponse.json(coverage)),
  http.get(`${BASE}/analytics/flaky`, () => HttpResponse.json(flaky)),
  http.get(`${BASE}/analytics/heatmap`, () => HttpResponse.json(heatmap)),
  http.get(`${BASE}/analytics/readiness`, () => HttpResponse.json(readiness)),

  // Runs
  http.get(`${BASE}/runs`, () => HttpResponse.json(runs)),
  http.get(`${BASE}/runs/:runId`, ({ params }) =>
    HttpResponse.json({ id: params["runId"], status: "PASS" }),
  ),
  http.get(`${BASE}/runs/:runId/steps`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/runs/:runId/logs`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/runs/:runId/artifacts`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/runs/:runId/artifacts/:artifactId`, ({ params }) =>
    HttpResponse.json({
      artifact_id: params["artifactId"],
      url: "https://example.invalid/blob/fake",
      kind: "SCREENSHOT",
      scheme: "https",
      expiresAt: "2099-01-01T00:00:00Z",
    }),
  ),

  // Test cases
  http.get(`${BASE}/test-cases`, () => HttpResponse.json(cases)),
  http.get(`${BASE}/test-cases/:caseId`, ({ params }) => {
    const publicId = String(params["caseId"]);
    return HttpResponse.json({
      id: `case_${publicId}`,
      public_id: publicId,
      name: "Checkout flow rejects expired cards",
      description: "Verify expired card path returns a friendly error.",
      preconditions: "User signed in with no saved payment method.",
      priority: "P1",
      status: "ACTIVE",
      source: "MANUAL",
      suite_id: "ste_smoke",
      owner_id: null,
      tags: ["checkout", "billing"],
      steps: [
        {
          id: "stp_01",
          case_id: `case_${publicId}`,
          order: 1,
          action: "Navigate to /checkout",
          expected: "Checkout page loads",
          executable: true,
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
          code: null,
          data: null,
        },
        {
          id: "stp_02",
          case_id: `case_${publicId}`,
          order: 2,
          action: "Enter card 4000 0000 0000 0002 (expired)",
          expected: "Form shows 'expired card' error",
          executable: true,
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
          code: "await page.fill('#card', '4000000000000002')",
          data: null,
        },
      ],
      created_at: "2026-05-01T08:00:00Z",
      updated_at: "2026-05-25T14:30:00Z",
    });
  }),
  http.get(`${BASE}/test-cases/:caseId/steps`, () => HttpResponse.json({ items: [] })),

  // Defects
  http.get(`${BASE}/defects`, () => HttpResponse.json(defects)),
  http.get(`${BASE}/defects/:defectId`, ({ params }) =>
    HttpResponse.json({ id: params["defectId"], public_id: params["defectId"], title: "Fixture defect" }),
  ),
  http.get(`${BASE}/defects/:defectId/timeline`, () => HttpResponse.json({ items: [] })),

  // Documents
  http.get(`${BASE}/documents`, () => HttpResponse.json(docs)),
  http.get(`${BASE}/documents/:documentId`, ({ params }) =>
    HttpResponse.json({ id: params["documentId"], title: "Fixture doc" }),
  ),

  // Integrations
  http.get(`${BASE}/integrations`, () => HttpResponse.json(integrations)),
  http.get(`${BASE}/integrations/:integrationId`, ({ params }) =>
    HttpResponse.json({ id: params["integrationId"], kind: "JIRA", status: "CONNECTED" }),
  ),

  // Traceability
  http.get(`${BASE}/traceability/matrix`, () => HttpResponse.json(traceability)),

  // Projects / workspaces / requirements / suites (thin stubs)
  http.get(`${BASE}/projects`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/projects/:projectId`, ({ params }) =>
    HttpResponse.json({ id: params["projectId"], name: "Fixture project" }),
  ),
  http.get(`${BASE}/workspaces`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/workspaces/:workspaceId`, ({ params }) =>
    HttpResponse.json({ id: params["workspaceId"], name: "Fixture workspace" }),
  ),
  http.get(`${BASE}/workspaces/:workspaceId/members`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/requirements`, () => HttpResponse.json({ items: [] })),
  http.get(`${BASE}/requirements/:requirementId`, ({ params }) =>
    HttpResponse.json({ id: params["requirementId"], title: "Fixture requirement" }),
  ),
  http.get(`${BASE}/suites`, () => HttpResponse.json(suites)),
  http.get(`${BASE}/suites/:suiteId`, ({ params }) =>
    HttpResponse.json({ id: params["suiteId"], name: "Fixture suite" }),
  ),

  // Auth
  http.get(`${BASE}/auth/me`, () => HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev" })),

  // ----------------------------------------------------------------------
  // M1a stubs — endpoints referenced by the M1b screens but not yet served
  // by the real backend. Tests can override these via `server.use(...)`.
  // ----------------------------------------------------------------------
  // /audit-logs — M1a has the table but no public endpoint.
  http.get(`${BASE}/audit-logs`, () => HttpResponse.json({ items: [] })),
  // /inbox — M1b feature; backend lands in M2. Seeded from a static fixture so
  // unit tests can override per-test via `server.use(...)` for empty/error.
  http.get(`${BASE}/inbox`, () => HttpResponse.json(inbox)),
  // /runs/summary — derived view; backend ships later.
  http.get(`${BASE}/runs/summary`, () =>
    HttpResponse.json({
      activeNow: 0,
      today: 0,
      passed: 0,
      failed: 0,
      avgDurationMs: 0,
      queue: 0,
    }),
  ),
  // /runs/:id/network — M1b stub; HAR-driven view lands later.
  http.get(`${BASE}/runs/:runId/network`, () => HttpResponse.json({ items: [] })),
  // /mcp/providers — discovery endpoint comes in M2; ZERO bundled providers.
  http.get(`${BASE}/mcp/providers`, () => HttpResponse.json({ items: [] })),
];

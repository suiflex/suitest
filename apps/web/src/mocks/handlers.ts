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
import mcpProviders from "./fixtures/mcp-providers.json";
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

  // Runs — /summary must come before the /:runId param matcher.
  http.get(`${BASE}/runs/summary`, () =>
    HttpResponse.json({
      activeNow: 1,
      today: 24,
      passed: 22,
      failed: 2,
      avgDurationMs: 84000,
      queue: 3,
    }),
  ),
  http.get(`${BASE}/runs`, () => HttpResponse.json(runs)),
  http.get(`${BASE}/runs/:runId`, ({ params }) => {
    const publicId = String(params["runId"]);
    return HttpResponse.json({
      id: `run_${publicId}`,
      public_id: publicId,
      project_id: "prj_demo",
      name: "Checkout flow rejects expired cards",
      branch: "main",
      commit_sha: "abcd123",
      env: "staging",
      status: "FAIL",
      trigger: "MANUAL",
      tier_at_runtime: "ZERO",
      started_at: "2026-05-27T10:00:00Z",
      completed_at: "2026-05-27T10:01:14Z",
      duration_ms: 74000,
      summary: { total_steps: 4, passed_steps: 3, failed_steps: 1, duration_ms: 74000 },
      created_at: "2026-05-27T10:00:00Z",
      updated_at: "2026-05-27T10:01:14Z",
    });
  }),
  // M1d-32: cancel + rerun (handlers shipped in M1c, mocked here for tests)
  http.post(`${BASE}/runs/:runId/cancel`, ({ params }) => {
    const publicId = String(params["runId"]);
    return HttpResponse.json({
      id: `run_${publicId}`,
      public_id: publicId,
      project_id: "prj_demo",
      name: "Checkout flow rejects expired cards",
      branch: "main",
      commit_sha: "abcd123",
      env: "staging",
      status: "CANCELED",
      trigger: "MANUAL",
      tier_at_runtime: "ZERO",
      started_at: "2026-05-27T10:00:00Z",
      completed_at: "2026-05-27T10:00:30Z",
      duration_ms: 30000,
      summary: { total_steps: 4, passed_steps: 1, failed_steps: 0, duration_ms: 30000 },
      created_at: "2026-05-27T10:00:00Z",
      updated_at: "2026-05-27T10:00:30Z",
    });
  }),
  http.post(`${BASE}/runs/:runId/rerun`, () =>
    HttpResponse.json(
      {
        id: "run_RUN-502",
        public_id: "RUN-502",
        project_id: "prj_demo",
        name: "Checkout flow rejects expired cards",
        branch: "main",
        commit_sha: "abcd123",
        env: "staging",
        status: "QUEUED",
        trigger: "MANUAL",
        tier_at_runtime: "ZERO",
        started_at: null,
        completed_at: null,
        duration_ms: null,
        summary: null,
        created_at: "2026-05-30T17:00:00Z",
        updated_at: "2026-05-30T17:00:00Z",
      },
      { status: 201 },
    ),
  ),

  http.get(`${BASE}/runs/:runId/steps`, ({ params }) =>
    HttpResponse.json({
      items: [
        {
          id: "rs_01",
          run_id: `run_${String(params["runId"])}`,
          case_id: "case_01",
          case_public_id: "TC-101",
          step_order: 1,
          outcome: "PASS",
          started_at: "2026-05-27T10:00:00Z",
          completed_at: "2026-05-27T10:00:10Z",
          duration_ms: 10000,
          error_message: null,
        },
        {
          id: "rs_02",
          run_id: `run_${String(params["runId"])}`,
          case_id: "case_01",
          case_public_id: "TC-101",
          step_order: 2,
          outcome: "FAIL",
          started_at: "2026-05-27T10:00:10Z",
          completed_at: "2026-05-27T10:00:30Z",
          duration_ms: 20000,
          error_message: "AssertionError: expected 200 got 500",
        },
      ],
    }),
  ),
  http.get(`${BASE}/runs/:runId/logs`, () =>
    HttpResponse.json({
      lines: [
        "2026-05-27T10:00:00Z [INFO] Starting run",
        "2026-05-27T10:00:10Z [PASS] Step 1: Navigate /checkout",
        "2026-05-27T10:00:30Z [FAIL] Step 2: AssertionError 500",
      ],
      nextCursor: null,
    }),
  ),
  http.get(`${BASE}/runs/:runId/artifacts`, () =>
    HttpResponse.json({
      items: [
        {
          id: "art_01",
          run_step_id: "rs_02",
          kind: "SCREENSHOT",
          mime_type: "image/png",
          size_bytes: 102400,
          created_at: "2026-05-27T10:00:30Z",
        },
        {
          id: "art_02",
          run_step_id: "rs_02",
          kind: "HAR",
          mime_type: "application/json",
          size_bytes: 51200,
          created_at: "2026-05-27T10:00:30Z",
        },
      ],
    }),
  ),
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

  // M1-12: step write endpoints — thin stubs (per-test overrides via server.use)
  http.post(`${BASE}/test-cases/:caseId/steps`, ({ params }) => {
    const publicId = String(params["caseId"]);
    return HttpResponse.json(
      {
        id: `case_${publicId}`,
        public_id: publicId,
        name: "Checkout flow rejects expired cards",
        description: null,
        preconditions: null,
        priority: "P1",
        status: "ACTIVE",
        source: "MANUAL",
        suite_id: "ste_smoke",
        owner_id: null,
        tags: [],
        steps: [
          {
            id: "stp_new",
            case_id: `case_${publicId}`,
            order: 1,
            action: "",
            expected: "",
            executable: true,
            mcp_provider: "playwright-mcp",
            target_kind: "FE_WEB",
            code: null,
            data: null,
          },
        ],
        created_at: "2026-05-01T08:00:00Z",
        updated_at: "2026-05-25T14:30:00Z",
      },
      { status: 201 },
    );
  }),

  http.patch(`${BASE}/test-cases/:caseId/steps`, ({ params }) => {
    const publicId = String(params["caseId"]);
    return HttpResponse.json({
      id: `case_${publicId}`,
      public_id: publicId,
      name: "Checkout flow rejects expired cards",
      description: null,
      preconditions: null,
      priority: "P1",
      status: "ACTIVE",
      source: "MANUAL",
      suite_id: "ste_smoke",
      owner_id: null,
      tags: [],
      steps: [],
      created_at: "2026-05-01T08:00:00Z",
      updated_at: "2026-05-25T14:30:00Z",
    });
  }),

  // M1d-23: soft-delete + restore (204 No Content, idempotent)
  http.delete(`${BASE}/test-cases/:caseId`, () => new HttpResponse(null, { status: 204 })),
  http.post(`${BASE}/test-cases/:caseId/restore`, () => new HttpResponse(null, { status: 204 })),

  // M1-14: step reorder — returns the updated TestCaseDetail
  http.patch(`${BASE}/test-cases/:caseId/steps/reorder`, ({ params }) => {
    const publicId = String(params["caseId"]);
    return HttpResponse.json({
      id: `case_${publicId}`,
      public_id: publicId,
      name: "Checkout flow rejects expired cards",
      description: null,
      preconditions: null,
      priority: "P1",
      status: "ACTIVE",
      source: "MANUAL",
      suite_id: "ste_smoke",
      owner_id: null,
      tags: [],
      steps: [
        {
          id: "stp_02",
          case_id: `case_${publicId}`,
          order: 1,
          action: "Enter card 4000 0000 0000 0002 (expired)",
          expected: "Form shows 'expired card' error",
          executable: true,
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
          code: null,
          data: null,
        },
        {
          id: "stp_01",
          case_id: `case_${publicId}`,
          order: 2,
          action: "Navigate to /checkout",
          expected: "Checkout page loads",
          executable: true,
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
          code: null,
          data: null,
        },
      ],
      created_at: "2026-05-01T08:00:00Z",
      updated_at: "2026-05-25T14:30:00Z",
    });
  }),

  // M1-15b: bulk update test cases
  http.post(`${BASE}/test-cases/bulk-update`, () =>
    HttpResponse.json({ updated: 1, auditIds: ["aud_01"] }),
  ),

  // Defects
  http.get(`${BASE}/defects`, () => HttpResponse.json(defects)),
  http.get(`${BASE}/defects/:defectId`, ({ params }) => {
    const publicId = String(params["defectId"]);
    return HttpResponse.json({
      id: `def_${publicId}`,
      public_id: publicId,
      title: "Fixture defect",
      description: null,
      severity: "HIGH",
      status: "OPEN",
      agent_diagnosis_kind: "MANUAL_TRIAGE",
      run_public_id: "RUN-501",
      test_case_public_id: "TC-101",
      requirement_public_id: null,
      assignee_id: null,
      component: null,
      workspace_id: "ws_demo",
      external_issues: [],
      created_at: "2026-05-01T08:00:00Z",
      updated_at: "2026-05-25T14:30:00Z",
    });
  }),
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
  // Shape mirrors `MeResponse` in packages/shared/openapi.json — the real
  // backend returns the user plus every workspace membership they hold so
  // the Sidebar workspace picker and `useActiveWorkspace` seeder have data.
  http.get(`${BASE}/auth/me`, () =>
    HttpResponse.json({
      id: "550e8400-e29b-41d4-a716-446655440000",
      email: "maya@nusantararetail.local",
      name: "Maya Putri",
      avatar_url: null,
      must_change_password: false,
      is_superuser: false,
      memberships: [
        {
          workspace_id: "ws_1",
          role: "OWNER",
          workspace: {
            id: "ws_1",
            slug: "nusantara-retail",
            name: "Nusantara Retail",
          },
        },
      ],
    }),
  ),

  // ----------------------------------------------------------------------
  // M1a stubs — endpoints referenced by the M1b screens but not yet served
  // by the real backend. Tests can override these via `server.use(...)`.
  // ----------------------------------------------------------------------
  // /audit-logs — M1a has the table but no public endpoint.
  http.get(`${BASE}/audit-logs`, () => HttpResponse.json({ items: [] })),
  // /inbox — M1b feature; backend lands in M2. Seeded from a static fixture so
  // unit tests can override per-test via `server.use(...)` for empty/error.
  http.get(`${BASE}/inbox`, () => HttpResponse.json(inbox)),
  // /runs/:id/network — M1b stub; HAR-driven view lands later.
  http.get(`${BASE}/runs/:runId/network`, () => HttpResponse.json({ items: [] })),
  // /mcp/providers — registry CRUD (M2-6). Default mocks; per-test override
  // via `server.use`.
  http.get(`${BASE}/mcp/providers`, () => HttpResponse.json(mcpProviders)),
  http.get(`${BASE}/mcp/providers/:id`, ({ params }) =>
    HttpResponse.json({
      id: params["id"],
      name: "stub-mcp",
      kind: "custom",
      transport: "stdio",
      endpoint: "stub",
      healthStatus: "unknown",
      isBundled: false,
      enabled: true,
      tools: [],
      configJson: {},
      hasSecrets: false,
    }),
  ),
  http.post(`${BASE}/mcp/providers/test-connection`, () =>
    HttpResponse.json({
      ok: true,
      tools: [{ name: "echo", description: "echo back" }],
      serverVersion: "1.0.0",
    }),
  ),
  http.post(`${BASE}/mcp/providers`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: "mcp_new_stub",
        healthStatus: "unknown",
        isBundled: false,
        enabled: true,
        tools: [],
        configJson: {},
        hasSecrets: false,
        ...body,
      },
      { status: 201 },
    );
  }),
  http.patch(`${BASE}/mcp/providers/:id`, async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: params["id"],
      name: "stub-mcp",
      kind: "custom",
      transport: "stdio",
      endpoint: "stub",
      healthStatus: "unknown",
      isBundled: false,
      enabled: true,
      tools: [],
      configJson: {},
      hasSecrets: false,
      ...body,
    });
  }),
  http.delete(`${BASE}/mcp/providers/:id`, () => new HttpResponse(null, { status: 204 })),

  // ----------------------------------------------------------------------
  // M1e — auth/invitation/admin stubs. Per-test overrides via `server.use`.
  // ----------------------------------------------------------------------
  http.patch(`${BASE}/users/me/password`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${BASE}/workspaces/:workspaceId/invitations`, () => HttpResponse.json({ items: [] })),
  http.post(`${BASE}/workspaces/:workspaceId/invitations`, () =>
    HttpResponse.json(
      {
        id: "inv_stub",
        email: "invitee@example.test",
        role: "QA",
        expires_at: "2099-06-07T10:00:00Z",
        accepted_at: null,
        revoked_at: null,
        link: "http://localhost/accept-invite?token=stub",
      },
      { status: 201 },
    ),
  ),
  http.post(
    `${BASE}/invitations/:invitationId/revoke`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post(`${BASE}/invitations/:invitationId/resend`, () =>
    HttpResponse.json({
      id: "inv_stub",
      email: "invitee@example.test",
      role: "QA",
      expires_at: "2099-06-14T10:00:00Z",
      accepted_at: null,
      revoked_at: null,
      link: "http://localhost/accept-invite?token=resent-stub",
    }),
  ),
  http.post(`${BASE}/admin/users/:userId/reset-password`, () =>
    HttpResponse.json({ temporaryPassword: "Tmp-Stub-Pw1" }),
  ),
  http.get(`${BASE}/admin/password-reset-requests`, () => HttpResponse.json({ items: [] })),

  // ----------------------------------------------------------------------
  // M2-5 — deterministic generators. OpenAPI + crawler stream SSE; recorder
  // is plain request/response. Per-test overrides via `server.use`.
  // ----------------------------------------------------------------------
  http.post(`${BASE}/generators/openapi`, () => sseResponse(deterministicFrames("openapi"))),
  http.post(`${BASE}/generators/crawler`, () => sseResponse(deterministicFrames("crawler"))),
  http.post(`${BASE}/generators/recorder/sessions`, () =>
    HttpResponse.json({
      session_id: "rec_stub",
      ws_room: "recorder:rec_stub",
      browser_url: "http://localhost:9333/devtools",
      expires_at: "2099-06-01T10:30:00Z",
    }),
  ),
  http.post(`${BASE}/generators/recorder/sessions/:sessionId/finalize`, () =>
    HttpResponse.json({
      id: "tc_rec",
      public_id: "TC-9001",
      name: "Recorded session",
      description: null,
      status: "DRAFT",
      priority: "P2",
      source: "RECORDER",
      target_kind: "FE_WEB",
      suite_id: "ste_smoke",
      owner_id: null,
      tags: [],
      steps: [],
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:00:00Z",
    }),
  ),
  http.delete(
    `${BASE}/generators/recorder/sessions/:sessionId`,
    () => new HttpResponse(null, { status: 204 }),
  ),
];

// ---------------------------------------------------------------------------
// SSE helpers for the generator handlers.
// ---------------------------------------------------------------------------

/** Render `{event, data}` pairs as a single SSE-framed streaming response. */
function sseResponse(frames: { event: string; data: unknown }[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const f of frames) {
        controller.enqueue(
          encoder.encode(`event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`),
        );
      }
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}

/** A canonical progress → 2×case → complete lifecycle for the modal test. */
function deterministicFrames(kind: "openapi" | "crawler"): { event: string; data: unknown }[] {
  const phase = kind === "openapi" ? "parsed" : "crawling";
  return [
    { event: "progress", data: { phase, generator_run_id: "gen_stub" } },
    {
      event: "case",
      data: {
        public_id: "TC-2001",
        name: "GET /pets → 200",
        case_kind: "happy",
        tags: ["contract"],
      },
    },
    {
      event: "case",
      data: {
        public_id: "TC-2002",
        name: "GET /pets → schema valid",
        case_kind: "schema",
        tags: ["contract"],
      },
    },
    {
      event: "complete",
      data: {
        generator_run_id: "gen_stub",
        target_suite_id: "ste_smoke",
        cases_created: 2,
        public_ids: ["TC-2001", "TC-2002"],
        duration_ms: 42,
      },
    },
  ];
}

import axios, { type AxiosError, type AxiosInstance } from "axios";

import type { components, paths } from "@/lib/api-types";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ApiErrorBody {
  code?: string;
  message?: string;
}

// Test seam: in Vitest (jsdom) we need an absolute origin so the axios http
// adapter can be intercepted by MSW. Production browser code resolves the
// relative path against window.location.origin.
const TEST_ORIGIN = "http://localhost";
const isTestEnv = typeof process !== "undefined" && process.env["NODE_ENV"] === "test";

function createClient(): AxiosInstance {
  const inst = axios.create({
    baseURL: isTestEnv ? `${TEST_ORIGIN}/api/v1` : "/api/v1",
    withCredentials: true,
    timeout: 30_000,
    ...(isTestEnv ? { adapter: "http" as const } : {}),
  });

  // Request interceptor — attach the `X-Workspace-Id` header.
  //
  // The M1a backend's `require_workspace_membership` dep returns 400 when the
  // header is missing on every authenticated endpoint. We read from the
  // persisted active-workspace store synchronously (no React) so every
  // outbound axios call carries the header transparently.
  inst.interceptors.request.use((config) => {
    const wsId = useActiveWorkspace.getState().workspaceId;
    if (wsId && config.headers) {
      config.headers["X-Workspace-Id"] = wsId;
    }
    return config;
  });

  inst.interceptors.response.use(
    (response) => response,
    (err: AxiosError<ApiErrorBody>) => {
      const status = err.response?.status ?? 0;
      const code = err.response?.data?.code ?? "UNKNOWN";
      const message = err.response?.data?.message ?? err.message;
      // Only navigate to /login on 401 when the user is NOT already on the
      // login page. Without this guard the `_app.beforeLoad` 401 from
      // `/auth/me` would cause a full reload + double-redirect loop during
      // the brief render of `<Login>` while TanStack Router is still
      // resolving its own router-level redirect.
      if (
        status === 401 &&
        typeof window !== "undefined" &&
        !window.location.pathname.startsWith("/login") &&
        !window.location.pathname.startsWith("/accept-invite")
      ) {
        const next = encodeURIComponent(window.location.pathname);
        window.location.assign(`/login?next=${next}`);
      }
      const retryable = status === 0 || status >= 500;
      throw new ApiError(status, code, message, retryable);
    },
  );

  return inst;
}

export const api: AxiosInstance = createClient();
export type Paths = paths;

// ---------------------------------------------------------------------------
// Typed REST helpers — thin wrappers around `api.get`. Screens that don't
// need the full `useQuery` lifecycle (e.g. one-shot signed-URL fetches) call
// these directly. Each helper returns the OpenAPI-generated body shape.
// ---------------------------------------------------------------------------

type RunDetail = components["schemas"]["RunDetail"];
type RunStepPublic = components["schemas"]["RunStepPublic"];
type ArtifactPublic = components["schemas"]["ArtifactPublic"];
type ArtifactSignedUrl = components["schemas"]["ArtifactSignedUrl"];

/** ``GET /runs/:id`` — full run detail incl. computed summary. */
export async function fetchRun(runId: string): Promise<RunDetail> {
  const res = await api.get<RunDetail>(`/runs/${runId}`);
  return res.data;
}

/** ``GET /runs/:id/steps`` — every recorded step (no pagination in M1c).
 * The endpoint returns a BARE array (`list[RunStepPublic]`), so wrap it. */
export async function fetchRunSteps(runId: string): Promise<{ items: RunStepPublic[] }> {
  const res = await api.get<RunStepPublic[] | { items: RunStepPublic[] }>(`/runs/${runId}/steps`);
  return { items: Array.isArray(res.data) ? res.data : res.data.items };
}

/** ``GET /runs/:id/artifacts`` — bare array (`list[ArtifactPublic]`); wrap it. */
export async function fetchRunArtifacts(runId: string): Promise<{ items: ArtifactPublic[] }> {
  const res = await api.get<ArtifactPublic[] | { items: ArtifactPublic[] }>(
    `/runs/${runId}/artifacts`,
  );
  return { items: Array.isArray(res.data) ? res.data : res.data.items };
}

/** ``GET /runs/:id/artifacts/:artifactId`` — presigned S3 URL + metadata. */
export async function fetchRunSignedUrl(
  runId: string,
  artifactId: string,
): Promise<ArtifactSignedUrl> {
  const res = await api.get<ArtifactSignedUrl>(`/runs/${runId}/artifacts/${artifactId}`);
  return res.data;
}

/** Generated test source for the run-detail Code tab (Phase 2 lifecycle ingest). */
interface TestCaseCode {
  automation_code?: string | null;
  automationCode?: string | null;
  description?: string | null;
}

/** ``GET /test-cases/:id`` — read just the persisted generated source. */
export async function fetchTestCaseCode(caseId: string): Promise<string | null> {
  const res = await api.get<TestCaseCode>(`/test-cases/${caseId}`);
  return res.data.automation_code ?? res.data.automationCode ?? null;
}

/** ``GET /test-cases/:id`` — read just the human-readable case description. */
export async function fetchTestCaseDescription(caseId: string): Promise<string | null> {
  const res = await api.get<TestCaseCode>(`/test-cases/${caseId}`);
  return res.data.description ?? null;
}

type RunLogPage = components["schemas"]["RunLogPage"];

/** ``GET /runs/:id/logs`` — persisted log stream (M4-10 time-travel replay reads this). */
export async function fetchRunLogs(runId: string, limit = 500): Promise<RunLogPage> {
  const res = await api.get<RunLogPage>(`/runs/${runId}/logs`, { params: { limit } });
  return res.data;
}

// ---------------------------------------------------------------------------
// Time-travel replay state delta (M5-1).
// ---------------------------------------------------------------------------

/** One key-level change in a step's state vs. the previous step. */
export interface StateChange {
  path: string;
  op: "added" | "removed" | "changed";
  before?: string | null;
  after?: string | null;
}

/** One replay step with its captured snapshot + computed delta. */
export interface RunReplayStep {
  id: string;
  stepOrder: number;
  casePublicId: string;
  outcome: string;
  durationMs?: number | null;
  startedAt?: string | null;
  errorMessage?: string | null;
  stateSnapshot?: Record<string, unknown> | null;
  delta: StateChange[];
}

export interface RunReplay {
  runId: string;
  steps: RunReplayStep[];
}

/** ``GET /runs/:id/replay`` — ordered steps + per-step state delta (M5-1). */
export async function fetchRunReplay(runId: string): Promise<RunReplay> {
  const res = await api.get<RunReplay>(`/runs/${runId}/replay`);
  return res.data;
}

// ---------------------------------------------------------------------------
// Workspace prompt forks — DB override layer over file defaults (M5-3).
// ---------------------------------------------------------------------------

export interface PromptDefault {
  name: string;
  baseVersion: string;
  hasActiveFork: boolean;
  activeForkVersion?: number | null;
}

export interface PromptFork {
  id: string;
  promptName: string;
  baseVersion: string;
  forkVersion: number;
  label?: string | null;
  isActive: boolean;
  hash: string;
  content?: string | null;
  createdAt: string;
}

export interface PromptDetail {
  name: string;
  baseVersion: string;
  defaultContent: string;
  forks: PromptFork[];
}

/** ``GET /prompts`` — overridable defaults + per-workspace fork status. */
export async function fetchPrompts(): Promise<PromptDefault[]> {
  const res = await api.get<{ items: PromptDefault[] }>("/prompts");
  return res.data.items;
}

/** ``GET /prompts/:name`` — default content + the workspace's fork history. */
export async function fetchPromptDetail(name: string): Promise<PromptDetail> {
  const res = await api.get<PromptDetail>(`/prompts/${name}`);
  return res.data;
}

/** ``POST /prompts/:name/forks`` — create (and by default activate) a fork. */
export async function createPromptFork(
  name: string,
  body: { content: string; label?: string; activate?: boolean },
): Promise<PromptFork> {
  const res = await api.post<PromptFork>(`/prompts/${name}/forks`, body);
  return res.data;
}

/** ``POST /prompts/forks/:id/activate`` — make a fork the active override. */
export async function activatePromptFork(overrideId: string): Promise<PromptFork> {
  const res = await api.post<PromptFork>(`/prompts/forks/${overrideId}/activate`);
  return res.data;
}

/** ``DELETE /prompts/forks/:id`` — delete a fork (reverts to default if active). */
export async function deletePromptFork(overrideId: string): Promise<void> {
  await api.delete(`/prompts/forks/${overrideId}`);
}

// ---------------------------------------------------------------------------
// Prompt A/B experiments (M5-4).
// ---------------------------------------------------------------------------

export interface ExperimentVariantStats {
  variant: "A" | "B";
  overrideId?: string | null;
  impressions: number;
  successes: number;
  conversionPct: number;
}

export interface PromptExperiment {
  id: string;
  promptName: string;
  status: string;
  splitPct: number;
  variantA: ExperimentVariantStats;
  variantB: ExperimentVariantStats;
  winner?: "A" | "B" | null;
  createdAt: string;
}

/** ``GET /prompt-experiments`` — workspace A/B experiments with live stats. */
export async function fetchPromptExperiments(): Promise<PromptExperiment[]> {
  const res = await api.get<{ items: PromptExperiment[] }>("/prompt-experiments");
  return res.data.items;
}

/** ``POST /prompt-experiments`` — start an A/B test (override id null = default). */
export async function createPromptExperiment(body: {
  prompt_name: string;
  variant_a_override_id?: string | null;
  variant_b_override_id?: string | null;
  split_pct?: number;
}): Promise<PromptExperiment> {
  const res = await api.post<PromptExperiment>("/prompt-experiments", body);
  return res.data;
}

/** ``POST /prompt-experiments/:id/stop`` — stop an experiment. */
export async function stopPromptExperiment(id: string): Promise<PromptExperiment> {
  const res = await api.post<PromptExperiment>(`/prompt-experiments/${id}/stop`);
  return res.data;
}

/** ``POST /prompt-experiments/:id/outcome`` — record a variant outcome. */
export async function recordExperimentOutcome(
  id: string,
  body: { variant: "A" | "B"; success: boolean },
): Promise<PromptExperiment> {
  const res = await api.post<PromptExperiment>(`/prompt-experiments/${id}/outcome`, body);
  return res.data;
}

// ---------------------------------------------------------------------------
// Eval suite — golden datasets, runs, score-regression dashboard (M5-2).
// ---------------------------------------------------------------------------

export interface EvalSuiteInfo {
  suite: string;
  fixtures: number;
}

export interface EvalRunListItem {
  id: string;
  suiteName: string;
  fixturesCount: number;
  passed: number;
  failed: number;
  scorePct: number;
  modelId: string;
  runAt: string;
}

export interface EvalFixtureResult {
  suite: string;
  fixture: string;
  passed: boolean;
  detail: string;
}

export interface EvalRunPublic {
  id: string;
  suiteName: string;
  fixturesCount: number;
  passed: number;
  failed: number;
  modelId: string;
  runAt: string;
  results: EvalFixtureResult[];
}

/** ``GET /eval/fixtures`` — bundled golden datasets the weekly CI scores. */
export async function fetchEvalFixtures(): Promise<EvalSuiteInfo[]> {
  const res = await api.get<{ items: EvalSuiteInfo[] }>("/eval/fixtures");
  return res.data.items;
}

/** ``GET /eval/runs`` — newest-first eval run history for the dashboard. */
export async function fetchEvalRuns(suite?: string): Promise<EvalRunListItem[]> {
  const res = await api.get<{ items: EvalRunListItem[] }>("/eval/runs", {
    params: suite ? { suite } : undefined,
  });
  return res.data.items;
}

/** ``POST /eval/runs`` — run the deterministic eval suite (ADMIN+). */
export async function createEvalRun(suiteName = "default"): Promise<EvalRunPublic> {
  const res = await api.post<EvalRunPublic>("/eval/runs", { suite_name: suiteName });
  return res.data;
}

// ---------------------------------------------------------------------------
// MCP provider browser (Integrations screen, M1c task 20).
// ---------------------------------------------------------------------------

/** Summary row returned by ``GET /mcp/providers`` (one entry per provider). */
export interface McpProviderSummary {
  id: string;
  name: string;
  kind: string;
  transport: string;
  endpoint?: string;
  healthStatus: "ok" | "degraded" | "down" | "unknown";
  lastHealthAt?: string | null;
  isBundled?: boolean;
  tools?: { name: string }[];
}

/**
 * Detail returned by ``GET /mcp/providers/:id``. The tool list comes from the
 * discovery endpoint on the MCP server itself (cached server-side). M1c
 * surfaces it read-only; the "try it" form lands in M2.
 */
export interface McpProviderTool {
  name: string;
  description?: string;
  argSchema?: Record<string, unknown> | null;
}

export interface McpProviderDetail extends McpProviderSummary {
  tools: McpProviderTool[];
  configJson?: Record<string, unknown>;
  hasSecrets?: boolean;
  isDefaultForTarget?: Record<string, boolean>;
  enabled?: boolean;
}

export type McpTransport = "stdio" | "sse" | "ws";

/** Body for ``POST /mcp/providers`` — custom MCP registration (M2-6 / M2-7). */
export interface McpProviderWriteBody {
  name: string;
  kind: string;
  endpoint: string;
  transport: McpTransport;
  configJson?: Record<string, unknown>;
  secretsJson?: Record<string, unknown> | string | null;
  isDefaultForTarget?: Record<string, boolean>;
}

/** Backwards-compat envelope — backend returns `{ items: [...] }`. */
interface McpProvidersEnvelope {
  items: McpProviderSummary[];
}

export async function fetchMcpProviders(): Promise<McpProviderSummary[]> {
  const res = await api.get<McpProvidersEnvelope>("/mcp/providers");
  return res.data.items;
}

export async function fetchMcpProvider(id: string): Promise<McpProviderDetail> {
  const res = await api.get<McpProviderDetail>(`/mcp/providers/${id}`);
  return res.data;
}

export async function createMcpProvider(body: McpProviderWriteBody): Promise<McpProviderDetail> {
  const res = await api.post<McpProviderDetail>("/mcp/providers", body);
  return res.data;
}

export async function updateMcpProvider(
  id: string,
  body: Partial<McpProviderWriteBody> & { enabled?: boolean },
): Promise<McpProviderDetail> {
  const res = await api.patch<McpProviderDetail>(`/mcp/providers/${id}`, body);
  return res.data;
}

export async function deleteMcpProvider(id: string): Promise<void> {
  await api.delete(`/mcp/providers/${id}`);
}

/** Result of ``POST /mcp/providers/test-connection`` — dry-run discovery (M2-7). */
export interface McpProbeResult {
  ok: boolean;
  tools: { name: string; description?: string }[];
  serverVersion?: string | null;
}

export async function testMcpConnection(body: McpProviderWriteBody): Promise<McpProbeResult> {
  const res = await api.post<McpProbeResult>("/mcp/providers/test-connection", body);
  return res.data;
}

/** Result of ``POST /mcp/providers/:id/invoke`` — ad-hoc tool call (M2-8). */
export interface McpInvokeResult {
  ok: boolean;
  output: Record<string, unknown>;
  stdout: string;
  stderr: string;
  durationMs: number;
  error?: string | null;
}

export async function discoverMcpProviderTools(id: string): Promise<McpProviderDetail> {
  const res = await api.post<McpProviderDetail>(`/mcp/providers/${id}/discover`);
  return res.data;
}

export async function invokeMcpTool(
  id: string,
  body: { tool: string; arguments: Record<string, unknown> },
): Promise<McpInvokeResult> {
  const res = await api.post<McpInvokeResult>(`/mcp/providers/${id}/invoke`, body);
  return res.data;
}

/** One effective ``target_kind`` -> provider routing row (M2-9). */
export interface McpRoutingRule {
  targetKind: string;
  primary: string;
  fallback?: string | null;
  isOverride: boolean;
}

export type McpRoutingOverrides = Record<string, { primary: string; fallback?: string | null }>;

export async function fetchMcpRouting(): Promise<McpRoutingRule[]> {
  const res = await api.get<{ items: McpRoutingRule[] }>("/mcp/routing");
  return res.data.items;
}

export async function updateMcpRouting(overrides: McpRoutingOverrides): Promise<McpRoutingRule[]> {
  const res = await api.put<{ items: McpRoutingRule[] }>("/mcp/routing", { overrides });
  return res.data.items;
}

// ---------------------------------------------------------------------------
// Workspace LLM config — Settings → LLM (M3-2). Keys are write-only: requests
// send `apiKey`, responses only ever return `apiKeyHint`.
// ---------------------------------------------------------------------------

/** Active LLM config (`GET /workspaces/:id/llm-config`); key redacted. */
export interface LlmConfigPublic {
  id: string;
  provider: string;
  model: string;
  apiKeyHint: string | null;
  config: Record<string, unknown>;
  isActive: boolean;
  tier: "ZERO" | "LOCAL" | "CLOUD";
  lastValidatedAt: string | null;
}

/** Body for `PUT`/`POST :id/test`. `apiKey` is write-only. */
export interface LlmConfigWriteBody {
  provider: string;
  model: string;
  apiKey?: string;
  config?: Record<string, unknown>;
}

export interface LlmTestResult {
  ok: boolean;
  latencyMs: number;
  modelEcho?: string | null;
  error?: { code: string; message: string } | null;
}

export interface LlmModel {
  id: string;
  name: string;
  contextWindow?: number;
  maxOutput?: number;
}

export async function fetchLlmConfig(workspaceId: string): Promise<LlmConfigPublic | null> {
  try {
    const res = await api.get<LlmConfigPublic>(`/workspaces/${workspaceId}/llm-config`);
    return res.data;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function putLlmConfig(
  workspaceId: string,
  body: LlmConfigWriteBody,
): Promise<LlmConfigPublic> {
  const res = await api.put<LlmConfigPublic>(`/workspaces/${workspaceId}/llm-config`, body);
  return res.data;
}

export async function testLlmConfig(
  workspaceId: string,
  body: LlmConfigWriteBody,
): Promise<LlmTestResult> {
  const res = await api.post<LlmTestResult>(`/workspaces/${workspaceId}/llm-config/test`, body);
  return res.data;
}

export async function deleteLlmConfig(workspaceId: string): Promise<void> {
  await api.delete(`/workspaces/${workspaceId}/llm-config`);
}

export async function fetchLlmModels(workspaceId: string, provider: string): Promise<LlmModel[]> {
  const res = await api.get<{ provider: string; models: LlmModel[] }>(
    `/workspaces/${workspaceId}/llm-config/models`,
    { params: { provider } },
  );
  return res.data.models;
}

// ---------------------------------------------------------------------------
// Workspace cost tracking (M3-14) — Insights → Cost.
// ---------------------------------------------------------------------------

export interface ProviderCost {
  provider: string;
  costUsd: number;
  tokensIn: number;
  tokensOut: number;
  sessions: number;
}

export interface WorkspaceCost {
  totalCostUsd: number;
  totalTokensIn: number;
  totalTokensOut: number;
  sessionCount: number;
  windowDays: number;
  byProvider: ProviderCost[];
  byKind: { kind: string; costUsd: number; sessions: number }[];
  budget: {
    dailyCapUsd: number;
    todaySpendUsd: number;
    overBudget: boolean;
    alert: string | null;
  };
}

export async function fetchWorkspaceCost(
  workspaceId: string,
  windowDays = 30,
): Promise<WorkspaceCost> {
  const res = await api.get<WorkspaceCost>(`/workspaces/${workspaceId}/cost`, {
    params: { windowDays },
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Workspace autonomy (M3-15 / M3-16) — Settings → Automation.
// ---------------------------------------------------------------------------

export type AutonomyLevel = "manual" | "assist" | "semi_auto" | "auto";

/** `GET`/`PUT /workspaces/:id/autonomy` — level + overrides + computed effective. */
export interface AutonomyState {
  level: AutonomyLevel;
  overrides: Record<string, boolean>;
  effective: Record<string, boolean>;
  tier: "ZERO" | "LOCAL" | "CLOUD";
  knownOverrideKeys: string[];
  updatedAt: string | null;
  updatedBy: string | null;
}

export interface AutonomyUpdateBody {
  level: AutonomyLevel;
  overrides: Record<string, boolean>;
  reason?: string;
}

export async function fetchAutonomy(workspaceId: string): Promise<AutonomyState> {
  const res = await api.get<AutonomyState>(`/workspaces/${workspaceId}/autonomy`);
  return res.data;
}

export async function putAutonomy(
  workspaceId: string,
  body: AutonomyUpdateBody,
): Promise<AutonomyState> {
  const res = await api.put<AutonomyState>(`/workspaces/${workspaceId}/autonomy`, body);
  return res.data;
}

// ---------------------------------------------------------------------------
// Public invitation onboarding (M1e).
// ---------------------------------------------------------------------------

export interface InvitationValidation {
  email: string;
  workspace_name: string;
  role: "ADMIN" | "QA" | "VIEWER";
  expires_at: string;
}

export interface AcceptInviteInput {
  token: string;
  name: string;
  password: string;
}

export async function validateInvitation(token: string): Promise<InvitationValidation> {
  const res = await api.get<InvitationValidation>("/invitations/validate", {
    params: { token },
  });
  return res.data;
}

export async function acceptInvitation(input: AcceptInviteInput): Promise<void> {
  await api.post("/auth/accept-invite", input);
}

// ---------------------------------------------------------------------------
// Authenticated M1e helpers — self-service password change, workspace
// invitation management (ADMIN+), member listing, super-admin user reset, and
// reset-request review.
//
// All types are derived from the OpenAPI-generated `components["schemas"]`;
// no `as any`. The backend uses one shared `Role` enum (ADMIN/OWNER/QA/VIEWER)
// for both invitations and memberships. Invite creation is limited to
// ADMIN/QA/VIEWER at the UI layer (see MembersPanel).
// ---------------------------------------------------------------------------

export type Role = components["schemas"]["Role"];
type ChangePasswordRequest = components["schemas"]["ChangePasswordRequest"];
type InvitationCreateRequest = components["schemas"]["InvitationCreateRequest"];
export type InvitationOut = components["schemas"]["InvitationOut"];
type InvitationListEnvelope = components["schemas"]["InvitationListEnvelope"];
export type WorkspaceMemberPublic = components["schemas"]["WorkspaceMemberPublic"];
type ResetPasswordResponse = components["schemas"]["ResetPasswordResponse"];
export type PasswordResetRequestOut = components["schemas"]["PasswordResetRequestOut"];
type PasswordResetRequestsEnvelope = components["schemas"]["PasswordResetRequestsEnvelope"];

/**
 * Derived lifecycle status for an invite. `InvitationOut` carries timestamps,
 * not a status field, so callers compute the badge from them.
 */
export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export function invitationStatus(inv: InvitationOut): InvitationStatus {
  if (inv.revoked_at) return "revoked";
  if (inv.accepted_at) return "accepted";
  if (new Date(inv.expires_at).getTime() <= Date.now()) return "expired";
  return "pending";
}

/** ``PATCH /users/me/password`` — change the current user's own password. */
export async function changeOwnPassword(input: ChangePasswordRequest): Promise<void> {
  await api.patch("/users/me/password", input);
}

/** ``POST /workspaces/:id/invitations`` — create invite, returns copyable link. */
export async function createInvitation(
  workspaceId: string,
  input: InvitationCreateRequest,
): Promise<InvitationOut> {
  const res = await api.post<InvitationOut>(`/workspaces/${workspaceId}/invitations`, input);
  return res.data;
}

/** ``GET /workspaces/:id/invitations`` — pending/accepted/revoked/expired. */
export async function listInvitations(workspaceId: string): Promise<InvitationOut[]> {
  const res = await api.get<InvitationListEnvelope>(`/workspaces/${workspaceId}/invitations`);
  return res.data.items;
}

/** ``POST /invitations/:id/revoke`` — revoke a pending invite (204). */
export async function revokeInvitation(invitationId: string): Promise<void> {
  await api.post(`/invitations/${invitationId}/revoke`);
}

// ---------------------------------------------------------------------------
// Test step reorder (M1-14).
// ---------------------------------------------------------------------------

type TestCaseDetail = components["schemas"]["TestCaseDetail"];

/**
 * ``PATCH /test-cases/:id/steps/reorder`` — atomic step reorder.
 * Body must contain every existing step id exactly once.
 */
export async function reorderSteps(
  caseId: string,
  stepIdsInOrder: string[],
): Promise<TestCaseDetail> {
  const res = await api.patch<TestCaseDetail>(`/test-cases/${caseId}/steps/reorder`, {
    stepIdsInOrder,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Bulk test-case operations (M1-15b).
// ---------------------------------------------------------------------------

type BulkUpdateRequest =
  | components["schemas"]["BulkDeleteRequest"]
  | components["schemas"]["BulkMoveToSuiteRequest"]
  | components["schemas"]["BulkSetPriorityRequest"]
  | components["schemas"]["BulkAddTagsRequest"]
  | components["schemas"]["BulkRemoveTagsRequest"];
type BulkUpdateResponse = components["schemas"]["BulkUpdateResponse"];

export type { BulkUpdateRequest, BulkUpdateResponse };

/** ``POST /test-cases/bulk-update`` — bulk delete / move / priority / tags. */
export async function bulkUpdate(body: BulkUpdateRequest): Promise<BulkUpdateResponse> {
  const res = await api.post<BulkUpdateResponse>("/test-cases/bulk-update", body);
  return res.data;
}

/** ``POST /invitations/:id/resend`` — rotate token + TTL, returns new link. */
export async function resendInvitation(invitationId: string): Promise<InvitationOut> {
  const res = await api.post<InvitationOut>(`/invitations/${invitationId}/resend`);
  return res.data;
}

/** ``GET /workspaces/:id/members`` — workspace member roster. */
export async function listMembers(workspaceId: string): Promise<WorkspaceMemberPublic[]> {
  const res = await api.get<WorkspaceMemberPublic[]>(`/workspaces/${workspaceId}/members`);
  return res.data;
}

/**
 * ``POST /admin/users/:id/reset-password`` — one-time temporary password.
 * The backend response field is `temporaryPassword` (camelCase).
 */
export async function adminResetPassword(userId: string): Promise<ResetPasswordResponse> {
  const res = await api.post<ResetPasswordResponse>(`/admin/users/${userId}/reset-password`);
  return res.data;
}

/**
 * Result of {@link listPasswordResetRequests}. The backend returns `503` with
 * `code: "ENCRYPTION_NOT_CONFIGURED"` when AES-GCM is not configured — reset
 * links can't be decrypted, so we surface that as a discriminated state rather
 * than re-throwing a raw `ApiError`.
 */
export type PasswordResetRequestsResult =
  | { encryptionConfigured: true; items: PasswordResetRequestOut[] }
  | { encryptionConfigured: false; items: [] };

/** ``GET /admin/password-reset-requests`` — interim super-admin review list. */
export async function listPasswordResetRequests(): Promise<PasswordResetRequestsResult> {
  try {
    const res = await api.get<PasswordResetRequestsEnvelope>("/admin/password-reset-requests");
    return { encryptionConfigured: true, items: res.data.items };
  } catch (err) {
    if (err instanceof ApiError && err.status === 503 && err.code === "ENCRYPTION_NOT_CONFIGURED") {
      return { encryptionConfigured: false, items: [] };
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Programmatic API keys — MCP / SDK / CI access (workspace-scoped).
// ---------------------------------------------------------------------------

export interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  /** Full token, decrypted server-side (admin list only); null for pre-0043 keys. */
  key?: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

/** Create response — carries the plaintext `key` exactly once. */
export interface ApiKeyCreated extends ApiKeyItem {
  key: string;
}

function requireWorkspaceId(): string {
  const ws = useActiveWorkspace.getState().workspaceId;
  if (!ws) throw new Error("No active workspace selected");
  return ws;
}

/** ``GET /workspaces/:id/api-keys`` — live keys, secrets never returned. */
export async function listApiKeys(): Promise<ApiKeyItem[]> {
  const ws = requireWorkspaceId();
  const res = await api.get<{ items: ApiKeyItem[] }>(`/workspaces/${ws}/api-keys`);
  return res.data.items;
}

/** ``POST /workspaces/:id/api-keys`` — mint a key; plaintext returned once. */
export async function createApiKey(name: string, expiresInDays?: number): Promise<ApiKeyCreated> {
  const ws = requireWorkspaceId();
  const res = await api.post<ApiKeyCreated>(`/workspaces/${ws}/api-keys`, {
    name,
    expires_in_days: expiresInDays ?? null,
  });
  return res.data;
}

/** ``DELETE /workspaces/:id/api-keys/:keyId`` — revoke a key. */
export async function revokeApiKey(id: string): Promise<void> {
  const ws = requireWorkspaceId();
  await api.delete(`/workspaces/${ws}/api-keys/${id}`);
}

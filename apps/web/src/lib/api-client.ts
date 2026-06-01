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

/** ``GET /runs/:id/steps`` — every recorded step (no pagination in M1c). */
export async function fetchRunSteps(runId: string): Promise<{ items: RunStepPublic[] }> {
  const res = await api.get<{ items: RunStepPublic[] }>(`/runs/${runId}/steps`);
  return res.data;
}

/** ``GET /runs/:id/artifacts`` — list of artifacts captured during the run. */
export async function fetchRunArtifacts(runId: string): Promise<{ items: ArtifactPublic[] }> {
  const res = await api.get<{ items: ArtifactPublic[] }>(`/runs/${runId}/artifacts`);
  return res.data;
}

/** ``GET /runs/:id/artifacts/:artifactId`` — presigned S3 URL + metadata. */
export async function fetchRunSignedUrl(
  runId: string,
  artifactId: string,
): Promise<ArtifactSignedUrl> {
  const res = await api.get<ArtifactSignedUrl>(`/runs/${runId}/artifacts/${artifactId}`);
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

export async function createMcpProvider(
  body: McpProviderWriteBody,
): Promise<McpProviderDetail> {
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

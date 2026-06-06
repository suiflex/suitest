/**
 * Official TypeScript SDK for the Suitest API (M4-6).
 *
 * A small, dependency-free `fetch`-based client over the Suitest REST API. The
 * surface tracks the OpenAPI schema served at `/openapi.json`; a fully generated
 * client can be produced from there, but this hand-written client keeps the
 * common flows ergonomic and dependency-light.
 *
 * @example
 * ```ts
 * import { SuitestClient } from "@suitest/sdk";
 * const client = new SuitestClient({ baseUrl: "https://suitest.example", token: "...", workspaceId: "ws_1" });
 * const cases = await client.listCases();
 * const run = await client.createRun({ projectId: "prj_1", name: "smoke", caseIds: [cases[0]!.id] });
 * const final = await client.waitForRun(run.id);
 * ```
 *
 * @packageDocumentation
 */

export interface SuitestClientOptions {
  baseUrl: string;
  token?: string;
  workspaceId?: string;
  /** Override the global `fetch` (e.g. for Node < 18 or testing). */
  fetch?: typeof fetch;
}

export interface TestCase {
  id: string;
  publicId?: string;
  name: string;
  [key: string]: unknown;
}

export interface Run {
  id: string;
  status: string;
  [key: string]: unknown;
}

export interface McpProvider {
  name: string;
  status?: string;
  [key: string]: unknown;
}

/** Thrown on a non-2xx API response. */
export class SuitestAPIError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`Suitest API error ${status}: ${JSON.stringify(body)}`);
    this.name = "SuitestAPIError";
  }
}

const TERMINAL_STATUSES = new Set(["PASSED", "FAILED", "CANCELLED", "ERROR"]);

export class SuitestClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: SuitestClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.headers = { Accept: "application/json" };
    if (opts.token) this.headers["Authorization"] = `Bearer ${opts.token}`;
    if (opts.workspaceId) this.headers["X-Workspace-Id"] = opts.workspaceId;
    this.fetchImpl = opts.fetch ?? globalThis.fetch;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers = { ...this.headers };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const resp = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await resp.text();
    const parsed: unknown = text ? JSON.parse(text) : null;
    if (!resp.ok) throw new SuitestAPIError(resp.status, parsed);
    return parsed as T;
  }

  health(): Promise<Record<string, unknown>> {
    return this.request("GET", "/health");
  }

  capabilities(): Promise<Record<string, unknown>> {
    return this.request("GET", "/capabilities");
  }

  async listCases(limit = 50): Promise<TestCase[]> {
    const page = await this.request<{ items?: TestCase[] }>(
      "GET",
      `/api/v1/test-cases?limit=${limit}`,
    );
    return page.items ?? [];
  }

  searchCases(query: string, limit = 10): Promise<Array<{ caseId: string; name: string; score: number }>> {
    const q = encodeURIComponent(query);
    return this.request("GET", `/api/v1/test-cases/search?q=${q}&limit=${limit}`);
  }

  createRun(params: {
    projectId: string;
    name: string;
    caseIds: string[];
    branch?: string;
  }): Promise<Run> {
    return this.request("POST", "/api/v1/runs", {
      projectId: params.projectId,
      name: params.name,
      selection: params.caseIds.map((caseId) => ({ caseId })),
      ...(params.branch ? { branch: params.branch } : {}),
    });
  }

  getRun(runId: string): Promise<Run> {
    return this.request("GET", `/api/v1/runs/${runId}`);
  }

  async waitForRun(runId: string, opts: { pollMs?: number; timeoutMs?: number } = {}): Promise<Run> {
    const pollMs = opts.pollMs ?? 2000;
    const deadline = Date.now() + (opts.timeoutMs ?? 600_000);
    for (;;) {
      const run = await this.getRun(runId);
      if (TERMINAL_STATUSES.has(String(run.status).toUpperCase()) || Date.now() >= deadline) {
        return run;
      }
      await new Promise((r) => setTimeout(r, pollMs));
    }
  }

  async listMcpProviders(): Promise<McpProvider[]> {
    const result = await this.request<McpProvider[] | { items?: McpProvider[] }>(
      "GET",
      "/api/v1/mcp/providers",
    );
    return Array.isArray(result) ? result : (result.items ?? []);
  }
}

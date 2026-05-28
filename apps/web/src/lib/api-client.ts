import axios, { type AxiosError, type AxiosInstance } from "axios";

import type { paths } from "@/lib/api-types";
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
        !window.location.pathname.startsWith("/login")
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

import axios, { type AxiosError, type AxiosInstance } from "axios";

import type { paths } from "@/lib/api-types";

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

  inst.interceptors.response.use(
    (response) => response,
    (err: AxiosError<ApiErrorBody>) => {
      const status = err.response?.status ?? 0;
      const code = err.response?.data?.code ?? "UNKNOWN";
      const message = err.response?.data?.message ?? err.message;
      if (status === 401 && typeof window !== "undefined") {
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

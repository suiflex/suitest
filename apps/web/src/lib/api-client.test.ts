import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api-client";
import { server } from "@/mocks/server";

describe("api-client", () => {
  beforeEach(() => {
    vi.stubGlobal("location", {
      pathname: "/dashboard",
      assign: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on 200 happy path", async () => {
    server.use(
      http.get("*/api/v1/ping", () => HttpResponse.json({ ok: true, value: 42 })),
    );

    const res = await api.get<{ ok: boolean; value: number }>("/ping");

    expect(res.status).toBe(200);
    expect(res.data).toEqual({ ok: true, value: 42 });
  });

  it("redirects to /login?next= on 401", async () => {
    server.use(
      http.get("*/api/v1/protected", () =>
        HttpResponse.json({ code: "UNAUTHORIZED", message: "nope" }, { status: 401 }),
      ),
    );

    await expect(api.get("/protected")).rejects.toBeInstanceOf(ApiError);

    expect(window.location.assign).toHaveBeenCalledWith(
      "/login?next=" + encodeURIComponent("/dashboard"),
    );
  });

  it("throws ApiError with retryable=true on 500", async () => {
    server.use(
      http.get("*/api/v1/boom", () =>
        HttpResponse.json({ code: "INTERNAL", message: "kaboom" }, { status: 500 }),
      ),
    );

    let caught: ApiError | null = null;
    try {
      await api.get("/boom");
    } catch (err) {
      caught = err as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.status).toBe(500);
    expect(caught?.code).toBe("INTERNAL");
    expect(caught?.retryable).toBe(true);
  });

  it("throws ApiError with code LLM_DISABLED and retryable=false on 400", async () => {
    server.use(
      http.get("*/api/v1/agent/generate", () =>
        HttpResponse.json(
          { code: "LLM_DISABLED", message: "LLM is disabled in ZERO tier" },
          { status: 400 },
        ),
      ),
    );

    let caught: ApiError | null = null;
    try {
      await api.get("/agent/generate");
    } catch (err) {
      caught = err as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.status).toBe(400);
    expect(caught?.code).toBe("LLM_DISABLED");
    expect(caught?.retryable).toBe(false);
    expect(caught?.message).toBe("LLM is disabled in ZERO tier");
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { CLOUD_CAPS, ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderInbox() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/inbox"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const FIXTURE = {
  unread: 2,
  items: [
    {
      id: "nf_01",
      kind: "GATING_FAIL",
      title: "Gating suite failed on main",
      body: "Smoke @ main reported 2 failing steps.",
      ref: "RUN-1002",
      createdAt: "2026-05-27T11:13:40Z",
      read: false,
    },
    {
      id: "nf_02",
      kind: "AGENT_DEFECT_FILED",
      title: "Agent filed a defect",
      body: "DEF-201 auto-filed.",
      ref: "DEF-201",
      createdAt: "2026-05-26T09:00:00Z",
      read: true,
    },
  ],
};

describe("Inbox screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", {
      pathname: "/inbox",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before /inbox resolves", async () => {
    server.use(
      http.get("*/api/v1/inbox", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(FIXTURE);
      }),
    );
    renderInbox();
    expect(await screen.findByTestId("inbox-skeleton")).toBeInTheDocument();
  });

  it("ZERO tier: hides AI-typed cards (AGENT_*) and shows only deterministic items", async () => {
    server.use(http.get("*/api/v1/inbox", () => HttpResponse.json(FIXTURE)));
    renderInbox();
    const list = await screen.findByTestId("inbox-list", undefined, { timeout: 3000 });
    expect(list.querySelectorAll('[data-testid="inbox-card"]').length).toBe(1);
    expect(list.querySelector('[data-kind="GATING_FAIL"]')).not.toBeNull();
    expect(list.querySelector('[data-kind="AGENT_DEFECT_FILED"]')).toBeNull();
  });

  it("CLOUD tier: renders both deterministic and agent cards", async () => {
    setCaps(CLOUD_CAPS);
    // Pin /capabilities so the RootLayout effect re-fetch doesn't downgrade
    // the seeded tier back to ZERO during the test.
    server.use(
      http.get("*/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/inbox", () => HttpResponse.json(FIXTURE)),
    );
    renderInbox();
    const list = await screen.findByTestId("inbox-list", undefined, { timeout: 3000 });
    expect(list.querySelectorAll('[data-testid="inbox-card"]').length).toBe(2);
    expect(list.querySelector('[data-kind="AGENT_DEFECT_FILED"]')).not.toBeNull();
  });

  it("renders the empty state when there are no items", async () => {
    server.use(
      http.get("*/api/v1/inbox", () => HttpResponse.json({ unread: 0, items: [] })),
    );
    renderInbox();
    expect(
      await screen.findByText(/Inbox is empty/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /inbox 500s", async () => {
    server.use(
      http.get("*/api/v1/inbox", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderInbox();
    expect(
      await screen.findByText(/Couldn't load inbox/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the unread badge when there are unread items", async () => {
    server.use(http.get("*/api/v1/inbox", () => HttpResponse.json(FIXTURE)));
    renderInbox();
    expect(
      await screen.findByTestId("inbox-unread", undefined, { timeout: 3000 }),
    ).toHaveTextContent("2 unread");
  });
});

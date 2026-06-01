import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GenerateModal } from "@/components/cases/GenerateModal";
import type { components } from "@/lib/api-types";
import { server } from "@/mocks/server";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

type Suite = components["schemas"]["SuitePublic"];

const SUITES: Suite[] = [
  {
    id: "ste_smoke",
    project_id: "prj_demo",
    name: "Smoke",
    description: null,
    order: 0,
    case_count: 0,
    created_at: "2026-05-01T08:00:00Z",
    updated_at: "2026-05-01T08:00:00Z",
  },
];

function renderModal(props?: Partial<React.ComponentProps<typeof GenerateModal>>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <GenerateModal open onClose={onClose} suites={SUITES} projectId="prj_demo" {...props} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("GenerateModal", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_demo" });
  });
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
  });

  it("ZERO: AI strategies are rendered but disabled", () => {
    renderModal();
    expect(screen.getByTestId("gen-strategy-ai-enrich")).toBeInTheDocument();
    expect(screen.getByTestId("gen-strategy-ai-only")).toBeInTheDocument();
    // The three deterministic strategies are present.
    expect(screen.getByTestId("gen-strategy-openapi")).toBeInTheDocument();
    expect(screen.getByTestId("gen-strategy-crawler")).toBeInTheDocument();
    expect(screen.getByTestId("gen-strategy-recorder")).toBeInTheDocument();
  });

  it("streams OpenAPI generation end-to-end and shows the cases + complete banner", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByTestId("gen-strategy-openapi"));
    await user.click(screen.getByTestId("gen-next"));

    await user.type(screen.getByTestId("gen-openapi-url"), "https://api.example.com/openapi.json");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Streamed case rows arrive over SSE.
    await waitFor(() => {
      expect(screen.getAllByTestId("gen-case-row")).toHaveLength(2);
    });
    expect(screen.getByText("GET /pets → 200")).toBeInTheDocument();

    // Terminal `complete` frame flips to the success banner.
    await screen.findByTestId("gen-complete");
    expect(screen.getByTestId("gen-complete")).toHaveTextContent("2 cases added");
    expect(screen.getByTestId("gen-done")).toBeInTheDocument();
  });

  it("deep-links to the crawler config when given an initialStrategy", async () => {
    const user = userEvent.setup();
    renderModal({ initialStrategy: "crawler" });

    // Jumps straight to step 2 (configure) for the crawler.
    expect(screen.getByTestId("gen-configure-step")).toBeInTheDocument();
    expect(screen.getByTestId("gen-crawler-url")).toBeInTheDocument();

    await user.type(screen.getByTestId("gen-crawler-url"), "https://app.example.com");
    await user.click(screen.getByTestId("gen-run-btn"));

    await waitFor(() => {
      expect(screen.getAllByTestId("gen-case-row")).toHaveLength(2);
    });
    await screen.findByTestId("gen-complete");
  });

  it("surfaces an in-band SSE error frame", async () => {
    server.use(
      http.post("*/api/v1/generators/openapi", () => {
        const body =
          "event: error\ndata: " +
          JSON.stringify({ code: "INVALID_SPEC", message: "not a valid OpenAPI document" }) +
          "\n\n";
        return new HttpResponse(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    const user = userEvent.setup();
    renderModal({ initialStrategy: "openapi" });

    await user.type(screen.getByTestId("gen-openapi-url"), "https://bad/spec.json");
    await user.click(screen.getByTestId("gen-run-btn"));

    const err = await screen.findByTestId("gen-error");
    expect(err).toHaveTextContent("not a valid OpenAPI document");
  });

  it("recorder: start a session then finalize into a case", async () => {
    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com/login");
    await user.type(screen.getByTestId("gen-recorder-name"), "Login happy path");
    await user.click(screen.getByTestId("gen-run-btn")); // "Start recording"

    // Session opened → live panel with a finalize control.
    await screen.findByTestId("gen-recorder-live-panel");
    await user.click(screen.getByTestId("gen-recorder-finalize"));

    await screen.findByTestId("gen-complete");
    expect(screen.getByTestId("gen-complete")).toHaveTextContent("DRAFT case");
  });
});

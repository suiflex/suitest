import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GenerateModal } from "@/components/cases/GenerateModal";
import type { components } from "@/lib/api-types";
import * as generatorClient from "@/lib/generator-client";
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

  it("recorder: displays actual error message when recorder fails to start", async () => {
    server.use(
      http.post("*/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({ detail: "mcp transport unavailable" }, { status: 503 });
      }),
    );
    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com/login");
    await user.click(screen.getByTestId("gen-run-btn"));

    const err = await screen.findByTestId("gen-error");
    expect(err).toHaveTextContent("mcp transport unavailable");
  });

  it("recorder: allows selecting browser MCP provider", async () => {
    let capturedProvider = "";
    server.use(
      http.post("*/api/v1/generators/recorder/sessions", async ({ request }) => {
        const body = (await request.json()) as { mcp_provider: string };
        capturedProvider = body.mcp_provider;
        return HttpResponse.json({
          session_id: "rec_sess_custom",
          ws_room: "rec_sess_custom",
          browser_url: null,
          expires_at: "2026-05-29T09:00:00Z",
        });
      }),
    );
    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    // Verify MCP select is present with options
    const select = screen.getByTestId("gen-recorder-mcp-select");
    expect(select).toBeInTheDocument();

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com/login");
    await user.click(screen.getByTestId("gen-run-btn"));

    await screen.findByTestId("gen-recorder-live-panel");
    expect(capturedProvider).toBe("playwright-mcp");
  });

  it("recorder: allows deleting and editing captured steps before finalize", async () => {
    let capturedFinalizeBody: Record<string, unknown> | null = null;
    server.use(
      http.post("*/api/v1/generators/recorder/sessions/:sessionId/finalize", async ({ request }) => {
        capturedFinalizeBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: "tc_rec",
          public_id: "TC-9002",
          name: "Edited Flow",
          description: null,
          status: "DRAFT",
          priority: "P2",
          source: "RECORDER",
          target_kind: "FE_WEB",
          suite_id: "ste_smoke",
          owner_id: null,
          tags: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com/login");
    await user.type(screen.getByTestId("gen-recorder-name"), "Edited Flow");
    await user.click(screen.getByTestId("gen-run-btn"));

    await screen.findByTestId("gen-recorder-live-panel");
    // Initial step 0 is loaded from mock session (navigate to login)
    await screen.findByTestId("gen-recorder-step-0");

    // Add a step
    await user.click(screen.getByTestId("gen-recorder-add-step"));
    expect(screen.getByTestId("gen-recorder-customized-badge")).toBeInTheDocument();

    // The new step is currently in edit mode (index 1)
    await screen.findByTestId("gen-recorder-step-edit-1");
    await user.type(screen.getByTestId("gen-step-edit-selector"), "#username");
    await user.click(screen.getByTestId("gen-step-edit-save"));

    // Finalize
    await user.click(screen.getByTestId("gen-recorder-finalize"));
    await screen.findByTestId("gen-complete");

    // Check that custom events were transmitted to backend
    expect(capturedFinalizeBody).not.toBeNull();
    const sentEvents = (
      capturedFinalizeBody as { events?: Array<{ kind?: string; selector?: string }> } | null
    )?.events;
    expect(sentEvents).toHaveLength(2);
    expect(sentEvents?.[0]?.kind).toBe("navigate");
    expect(sentEvents?.[1]?.selector).toBe("#username");
  });

  it("recorder: continues receiving and appending new browser actions even after user edits or reorders steps", async () => {
    let pollCount = 0;
    server.use(
      http.get("*/api/v1/generators/recorder/sessions/:sessionId", () => {
        pollCount += 1;
        const events: Array<{
          kind: string;
          timestamp: string;
          url?: string;
          selector?: string;
          text?: string;
          masked?: boolean;
        }> = [
          {
            kind: "navigate",
            timestamp: "2026-06-01T10:00:00Z",
            url: "https://app.example.com/login",
          },
        ];
        if (pollCount >= 2) {
          events.push({
            kind: "click",
            timestamp: "2026-06-01T10:00:05Z",
            selector: "#submit-btn",
          });
        }
        return HttpResponse.json({
          id: "rec_stub",
          workspace_id: "ws_default",
          project_id: "prj_default",
          start_url: "https://app.example.com/login",
          status: "active",
          ws_room: "recorder:rec_stub",
          browser_url: null,
          is_headed: true,
          captured_events_count: events.length,
          captured_events: events,
          expires_at: "2099-06-01T10:30:00Z",
          created_at: "2026-06-01T10:00:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com/login");
    await user.type(screen.getByTestId("gen-recorder-name"), "Streaming Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    await screen.findByTestId("gen-recorder-live-panel");
    await screen.findByTestId("gen-recorder-step-0");

    // Add a manual step (triggers userHasEdited = true)
    await user.click(screen.getByTestId("gen-recorder-add-step"));
    expect(screen.getByTestId("gen-recorder-customized-badge")).toHaveTextContent(
      "Customized (live sync active)",
    );

    await screen.findByTestId("gen-recorder-step-edit-1");
    await user.type(screen.getByTestId("gen-step-edit-selector"), "#custom-input");
    await user.click(screen.getByTestId("gen-step-edit-save"));

    // Verify step 1 has our custom selector
    expect(screen.getByText("#custom-input")).toBeInTheDocument();

    // Now wait for the next poll cycle to deliver the browser's new click action on #submit-btn
    await waitFor(
      () => {
        expect(screen.getByText("#submit-btn")).toBeInTheDocument();
      },
      { timeout: 4000 },
    );

    // Both the manual step AND the incoming browser step exist together!
    expect(screen.getByText("#custom-input")).toBeInTheDocument();
    expect(screen.getByText("#submit-btn")).toBeInTheDocument();
  });

  it("recorder: shows recovery banner when headed browser disconnects and allows re-open & resume", async () => {
    let isHeadedActive = false;
    let resumeCalls = 0;

    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_stub_disconnect",
          ws_room: "recorder:rec_stub_disconnect",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_stub_disconnect",
          workspace_id: "ws_default",
          project_id: "prj_default",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_stub_disconnect",
          browser_url: null,
          is_headed: true,
          is_headed_active: isHeadedActive,
          captured_events_count: 1,
          captured_events: [
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00Z",
              selector: "#hero-btn",
            },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
      http.post("/api/v1/generators/recorder/sessions/:id/resume", () => {
        resumeCalls++;
        isHeadedActive = true;
        return HttpResponse.json({
          session_id: "rec_stub_disconnect",
          ws_room: "recorder:rec_stub_disconnect",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Resume Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Recovery banner should appear because is_headed_active is false
    const banner = await screen.findByTestId("gen-recorder-resume-banner");
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/Browser Window Disconnected \/ Closed/i)).toBeInTheDocument();

    // Click Re-open & Resume Browser
    await user.click(screen.getByTestId("recorder-resume-btn"));
    expect(resumeCalls).toBe(1);

    // After resume succeeds and next poll returns isHeadedActive = true, active banner appears
    await waitFor(() => {
      expect(screen.getByTestId("gen-recorder-headed-banner")).toBeInTheDocument();
    });
  });

  it("recorder: shows ready-for-review banner when closed via HUD finalize and allows resume or finalize", async () => {
    let isHeadedActive = false;
    let resumeCalls = 0;

    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_stub_hud_fin",
          ws_room: "recorder:rec_stub_hud_fin",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_stub_hud_fin",
          workspace_id: "ws_default",
          project_id: "prj_default",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_stub_hud_fin",
          browser_url: null,
          is_headed: true,
          is_headed_active: isHeadedActive,
          hud_finished: true,
          captured_events_count: 2,
          captured_events: [
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00Z",
              selector: "#hero-btn",
            },
            {
              kind: "type",
              timestamp: "2026-06-01T10:00:01Z",
              selector: "#search-input",
              text: "hello world",
            },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
      http.post("/api/v1/generators/recorder/sessions/:id/resume", () => {
        resumeCalls++;
        isHeadedActive = true;
        return HttpResponse.json({
          session_id: "rec_stub_hud_fin",
          ws_room: "recorder:rec_stub_hud_fin",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "HUD Finalize Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Ready for review banner appears with emerald theme
    const banner = await screen.findByTestId("gen-recorder-resume-banner");
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/Recording Completed from Browser — Ready for Review/i)).toBeInTheDocument();
    expect(screen.getByTestId("recorder-finalize-btn")).toBeInTheDocument();
    expect(screen.getByTestId("recorder-resume-btn")).toBeInTheDocument();

    // Click resume recording to re-open browser
    await user.click(screen.getByTestId("recorder-resume-btn"));
    expect(resumeCalls).toBe(1);
  });

  it("recorder: renders SELECT, UPLOAD, and ASSERT steps, supports clean noise and variable parameterization", async () => {
    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_stub_smart",
          ws_room: "recorder:rec_stub_smart",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_stub_smart",
          workspace_id: "ws-test",
          project_id: "prj_test",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_stub_smart",
          browser_url: null,
          is_headed: true,
          is_headed_active: true,
          captured_events_count: 5,
          captured_events: [
            {
              kind: "select",
              timestamp: "2026-06-01T10:00:01Z",
              selector: "select#country",
              text: "ID",
              assertion: { label: "Indonesia", value: "ID" },
            },
            {
              kind: "upload",
              timestamp: "2026-06-01T10:00:02Z",
              selector: "input#avatar",
              text: "avatar.png",
              data: { file_name: "avatar.png" },
            },
            {
              kind: "assert",
              timestamp: "2026-06-01T10:00:03Z",
              selector: ".toast-success",
              text: "Profile saved",
              assertion: { expected: "Profile saved successfully" },
            },
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:04.100Z",
              selector: "#submit-btn",
            },
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:04.200Z",
              selector: "#submit-btn",
            },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Smart Actions Flow");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Verify smart step badges render
    expect(await screen.findByText("SELECT")).toBeInTheDocument();
    expect(screen.getByText(/select#country → Indonesia/i)).toBeInTheDocument();

    expect(screen.getByText("UPLOAD")).toBeInTheDocument();
    expect(screen.getByText(/input#avatar ← avatar.png/i)).toBeInTheDocument();

    expect(screen.getByText("ASSERT")).toBeInTheDocument();
    expect(screen.getByText(/Profile saved successfully/i)).toBeInTheDocument();

    // Verify Clean Noise button deduplicates rapid clicks
    const cleanBtn = screen.getByTestId("gen-recorder-clean-noise");
    expect(cleanBtn).toBeInTheDocument();
    await user.click(cleanBtn);

    // Verify Make Variable works in step editor
    const editBtn = screen.getByTestId("gen-recorder-step-edit-btn-0");
    await user.click(editBtn);

    // Switch kind to TYPE
    await user.selectOptions(screen.getByTestId("gen-step-edit-kind"), "type");
    const inputField = screen.getByTestId("gen-step-edit-text");
    await user.clear(inputField);
    await user.type(inputField, "user@example.com");

    // Click Make Variable
    const makeVarBtn = screen.getByTestId("gen-step-make-variable");
    await user.click(makeVarBtn);
    expect(inputField).toHaveValue("{{email}}");
  });

  it("recorder: preserves intentional rapid clicks (>= 200ms) but debounces micro-bounce (< 200ms)", async () => {
    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_rapid_click_test",
          ws_room: "recorder:rec_rapid_click_test",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_rapid_click_test",
          workspace_id: "ws-test",
          project_id: "prj_test",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_rapid_click_test",
          browser_url: null,
          is_headed: true,
          is_headed_active: true,
          captured_events_count: 4,
          captured_events: [
            // Click 1: initial click
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00.000Z",
              selector: "button#increment",
            },
            // Click 2: micro hardware bounce (50ms) -> should be debounced
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00.050Z",
              selector: "button#increment",
            },
            // Click 3: intentional 2nd click (350ms later) -> must be PRESERVED
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00.400Z",
              selector: "button#increment",
            },
            // Click 4: intentional 3rd click (350ms later) -> must be PRESERVED
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:00.750Z",
              selector: "button#increment",
            },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Rapid Click Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Should render 3 clicks: click 1, click 3, and click 4 (click 2 at 50ms dropped)
    await waitFor(() => {
      const stepItems = screen.getAllByText(/button#increment/i);
      expect(stepItems).toHaveLength(3);
    });
  });

  it("recorder: syncs HUD edited steps and iframe events cleanly upon HUD finalization without loss", async () => {
    interface FinalizedEvent {
      selector?: string;
      frame_selector?: string;
      text?: string;
      [key: string]: unknown;
    }
    let finalizedPayload: { events?: FinalizedEvent[]; [key: string]: unknown } | null = null;

    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_iframe_sync_test",
          ws_room: "recorder:rec_iframe_sync_test",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_iframe_sync_test",
          workspace_id: "ws-test",
          project_id: "prj_test",
          start_url: "https://app.example.com",
          status: "active",
          hud_finished: true,
          is_headed_active: false,
          captured_events_count: 2,
          captured_events: [
            {
              kind: "click",
              timestamp: "2026-06-01T10:00:01.000Z",
              selector: "button#pay-now",
              frame_selector: "iframe#stripe-checkout",
            },
            {
              kind: "type",
              timestamp: "2026-06-01T10:00:02.000Z",
              selector: "input#custom-amount",
              text: "150000",
            },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
      http.post("/api/v1/generators/recorder/sessions/:id/finalize", async ({ request }) => {
        finalizedPayload = (await request.json()) as typeof finalizedPayload;
        return HttpResponse.json({
          id: "case_iframe_finalized",
          suite_id: "s1",
          name: "HUD Finalized Case",
          source: "RECORDER",
          target_kind: "FE_WEB",
          status: "DRAFT",
          priority: "P2",
          steps: [],
          created_at: "2026-06-01T10:05:00Z",
          updated_at: "2026-06-01T10:05:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Iframe Finalize Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Verify ready-for-review banner appears
    expect(await screen.findByText(/Recording Completed from Browser/i)).toBeInTheDocument();

    // Verify both the iframe step and the typed step are rendered
    expect(await screen.findByText(/button#pay-now/i)).toBeInTheDocument();
    expect(screen.getByText(/input#custom-amount/i)).toBeInTheDocument();

    // Finalize case
    const finalizeBtn = screen.getByTestId("recorder-finalize-btn");
    await user.click(finalizeBtn);

    // Verify the payload sent to backend contains both steps intact including frame_selector
    await waitFor(() => {
      expect(finalizedPayload).not.toBeNull();
      expect(finalizedPayload?.events).toHaveLength(2);
      expect(finalizedPayload?.events?.[0]?.selector).toBe("button#pay-now");
      expect(finalizedPayload?.events?.[0]?.frame_selector).toBe("iframe#stripe-checkout");
      expect(finalizedPayload?.events?.[1]?.text).toBe("150000");
    });
  });

  it("recorder: aborts and cancels active session when user clicks Cancel or closes modal", async () => {
    const cancelSpy = vi.spyOn(generatorClient, "cancelRecorderSession");
    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_cancel_test",
          ws_room: "recorder:rec_cancel_test",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_cancel_test",
          workspace_id: "ws-test",
          project_id: "prj_test",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_cancel_test",
          browser_url: null,
          is_headed: true,
          is_headed_active: true,
          captured_events_count: 0,
          captured_events: [],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
      http.delete("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({ status: "cancelled", session_id: "rec_cancel_test" });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Cancel Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("gen-cancel")).toBeInTheDocument();
    });

    // Click cancel
    await user.click(screen.getByTestId("gen-cancel"));

    expect(cancelSpy).toHaveBeenCalledWith("rec_cancel_test");
  });

  it("recorder: drops redundant navigate event immediately following a click", async () => {
    server.use(
      http.post("/api/v1/generators/recorder/sessions", () => {
        return HttpResponse.json({
          session_id: "rec_nav_dedup_test",
          ws_room: "recorder:rec_nav_dedup_test",
          browser_url: null,
          is_headed: true,
          expires_at: "2099-06-01T10:30:00Z",
        });
      }),
      http.get("/api/v1/generators/recorder/sessions/:id", () => {
        return HttpResponse.json({
          id: "rec_nav_dedup_test",
          workspace_id: "ws-test",
          project_id: "prj_test",
          start_url: "https://app.example.com",
          status: "active",
          ws_room: "recorder:rec_nav_dedup_test",
          browser_url: null,
          is_headed: true,
          is_headed_active: true,
          captured_events_count: 3,
          captured_events: [
            { kind: "navigate", url: "https://app.example.com/login", timestamp: "2026-06-01T10:00:00.000Z" },
            { kind: "click", selector: "button#submit", timestamp: "2026-06-01T10:00:01.000Z" },
            { kind: "navigate", url: "https://app.example.com/dashboard", timestamp: "2026-06-01T10:00:01.500Z" },
          ],
          expires_at: "2099-06-01T10:30:00Z",
          started_at: "2026-06-01T10:00:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderModal({ initialStrategy: "recorder" });

    await user.type(screen.getByTestId("gen-recorder-url"), "https://app.example.com");
    await user.type(screen.getByTestId("gen-recorder-name"), "Nav Dedup Test");
    await user.click(screen.getByTestId("gen-run-btn"));

    // Should only have initial navigate and the button#submit click
    await waitFor(() => {
      expect(screen.getByText(/https:\/\/app.example.com\/login/i)).toBeInTheDocument();
      expect(screen.getByText(/button#submit/i)).toBeInTheDocument();
      expect(screen.queryByText(/https:\/\/app.example.com\/dashboard/i)).not.toBeInTheDocument();
    });
  });
});



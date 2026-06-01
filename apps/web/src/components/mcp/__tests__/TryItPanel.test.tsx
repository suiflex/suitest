import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { TryItPanel } from "@/components/mcp/TryItPanel";
import { server } from "@/mocks/server";

function renderPanel(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TryItPanel providerId="mcp_x" tools={[{ name: "echo" }]} />
    </QueryClientProvider>,
  );
}

describe("TryItPanel", () => {
  it("invokes the selected tool and shows the result", async () => {
    const captured: { tool: string; arguments: Record<string, unknown> }[] = [];
    server.use(
      http.post("*/api/v1/mcp/providers/mcp_x/invoke", async ({ request }) => {
        const body = (await request.json()) as { tool: string; arguments: Record<string, unknown> };
        captured.push(body);
        return HttpResponse.json({
          ok: true,
          output: {},
          stdout: JSON.stringify(body.arguments),
          stderr: "",
          durationMs: 5,
          error: null,
        });
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    const args = screen.getByTestId("tryit-args");
    await user.clear(args);
    await user.type(args, '{{"ping":"pong"}');
    await user.click(screen.getByTestId("tryit-invoke"));

    await waitFor(() => {
      expect(screen.getByTestId("tryit-result")).toHaveTextContent("OK");
    });
    expect(captured[0]).toEqual({ tool: "echo", arguments: { ping: "pong" } });
  });

  it("shows an empty-state when no tools are discovered", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <TryItPanel providerId="mcp_x" tools={[]} />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("tryit-no-tools")).toBeInTheDocument();
  });
});

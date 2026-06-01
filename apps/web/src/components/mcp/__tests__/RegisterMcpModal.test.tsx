import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RegisterMcpModal } from "@/components/mcp/RegisterMcpModal";
import { server } from "@/mocks/server";

function renderModal(onClose = vi.fn()): { onClose: ReturnType<typeof vi.fn> } {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RegisterMcpModal onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("RegisterMcpModal", () => {
  it("submits a create request and closes on success", async () => {
    const captured: Record<string, unknown>[] = [];
    server.use(
      http.post("*/api/v1/mcp/providers", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        captured.push(body);
        return HttpResponse.json({ id: "mcp_x", ...body }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.type(screen.getByTestId("mcp-name"), "payments-mcp");
    await user.clear(screen.getByTestId("mcp-kind"));
    await user.type(screen.getByTestId("mcp-kind"), "payments");
    await user.type(screen.getByTestId("mcp-endpoint"), "npx -y @acme/payments-mcp");
    await user.click(screen.getByTestId("mcp-submit"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(captured).toHaveLength(1);
    expect(captured[0]).toMatchObject({
      name: "payments-mcp",
      kind: "payments",
      endpoint: "npx -y @acme/payments-mcp",
      transport: "stdio",
    });
  });

  it("surfaces a server error without closing", async () => {
    server.use(
      http.post("*/api/v1/mcp/providers", () =>
        HttpResponse.json({ code: "CONFLICT", message: "already exists" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.type(screen.getByTestId("mcp-name"), "dup-mcp");
    await user.type(screen.getByTestId("mcp-endpoint"), "cmd");
    await user.click(screen.getByTestId("mcp-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("mcp-form-error")).toBeInTheDocument();
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});

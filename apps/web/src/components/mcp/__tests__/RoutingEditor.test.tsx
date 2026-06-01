import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RoutingEditor } from "@/components/mcp/RoutingEditor";
import { server } from "@/mocks/server";

function renderEditor(onClose = vi.fn()): { onClose: ReturnType<typeof vi.fn> } {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RoutingEditor onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("RoutingEditor", () => {
  it("saves an override for a toggled target kind", async () => {
    server.use(
      http.get("*/api/v1/mcp/providers", () =>
        HttpResponse.json({
          items: [
            { id: "1", name: "api-http-mcp", kind: "http", transport: "stdio", healthStatus: "ok" },
            { id: "2", name: "vendor-x", kind: "http", transport: "sse", healthStatus: "ok" },
          ],
        }),
      ),
      http.get("*/api/v1/mcp/routing", () =>
        HttpResponse.json({
          items: [
            { targetKind: "BE_REST", primary: "api-http-mcp", fallback: null, isOverride: false },
          ],
        }),
      ),
    );
    let putBody: unknown = null;
    server.use(
      http.put("*/api/v1/mcp/routing", async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ items: [] });
      }),
    );

    const user = userEvent.setup();
    const { onClose } = renderEditor();

    await waitFor(() => {
      expect(screen.getByTestId("routing-row-BE_REST")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("routing-toggle-BE_REST"));
    await user.selectOptions(screen.getByTestId("routing-primary-BE_REST"), "vendor-x");
    await user.click(screen.getByTestId("routing-save"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(putBody).toEqual({
      overrides: { BE_REST: { primary: "vendor-x", fallback: null } },
    });
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { McpProviderPill } from "@/components/shared/McpProviderPill";

describe("<McpProviderPill>", () => {
  it("renders name + transport label", () => {
    render(
      <McpProviderPill
        provider={{ name: "playwright-mcp", health: "healthy", transport: "stdio" }}
      />,
    );
    const pill = screen.getByTestId("mcp-provider-pill");
    expect(pill).toHaveTextContent("playwright-mcp");
    expect(pill).toHaveTextContent("stdio");
  });

  it.each([
    ["healthy", "bg-accent"],
    ["degraded", "bg-amber"],
    ["down", "bg-red"],
    ["unchecked", "bg-fg-4"],
  ] as const)("colors the health dot %s → %s", (health, klass) => {
    render(
      <McpProviderPill
        provider={{ name: "api-mcp", health, transport: "SSE" }}
      />,
    );
    expect(screen.getByTestId("mcp-provider-pill")).toHaveAttribute("data-health", health);
    expect(screen.getByTestId("mcp-provider-pill-dot").className).toContain(klass);
  });
});

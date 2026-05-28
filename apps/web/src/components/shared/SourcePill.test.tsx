import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcePill } from "@/components/shared/SourcePill";

describe("<SourcePill>", () => {
  it.each([
    ["MANUAL", "text-fg-3"],
    ["AI", "text-violet"],
    ["MCP", "text-blue"],
    ["IMPORT", "text-amber"],
  ] as const)("renders %s with correct class", (source, klass) => {
    render(<SourcePill source={source} />);
    const pill = screen.getByTestId("source-pill");
    expect(pill).toHaveAttribute("data-source", source);
    expect(pill).toHaveTextContent(source);
    expect(pill.className).toContain(klass);
  });
});

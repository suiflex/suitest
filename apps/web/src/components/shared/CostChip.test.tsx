import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CostChip } from "@/components/shared/CostChip";
import { formatCost, formatTokens } from "@/components/shared/cost-format";

describe("formatTokens", () => {
  it.each([
    [0, "0"],
    [1, "1"],
    [999, "999"],
    [1000, "1.0k"],
    [4234, "4.2k"],
    [12_500, "12.5k"],
    [1_000_000, "1.0M"],
    [-5, "0"],
  ] as const)("formats %i → %s", (input, expected) => {
    expect(formatTokens(input)).toBe(expected);
  });
});

describe("formatCost", () => {
  it("uses 4 decimals for sub-cent amounts", () => {
    expect(formatCost(0.0034)).toBe("$0.0034");
  });
  it("uses 3 decimals between 1¢ and $1", () => {
    expect(formatCost(0.034)).toBe("$0.034");
  });
  it("uses 2 decimals at or above $1", () => {
    expect(formatCost(1.234)).toBe("$1.23");
  });
  it("supports non-USD currency code prefix", () => {
    expect(formatCost(1.5, "EUR")).toBe("EUR 1.50");
  });
});

describe("<CostChip>", () => {
  it("renders tokens · cost in the default format", () => {
    render(<CostChip tokens={4234} cost={0.034} />);
    expect(screen.getByTestId("cost-chip")).toHaveTextContent("4.2k tokens · $0.034");
  });

  it("includes the provider prefix when provided", () => {
    render(<CostChip tokens={1000} cost={0.01} provider="anthropic" />);
    expect(screen.getByTestId("cost-chip")).toHaveTextContent(
      "anthropic · 1.0k tokens · $0.01",
    );
  });

  it("appends tool calls count and pluralizes", () => {
    render(<CostChip tokens={4234} cost={0.034} toolCalls={3} />);
    expect(screen.getByTestId("cost-chip")).toHaveTextContent("3 tool calls");
    const { rerender } = render(<CostChip tokens={1000} cost={0.01} toolCalls={1} />);
    rerender(<CostChip tokens={1000} cost={0.01} toolCalls={1} />);
    expect(
      screen.getAllByTestId("cost-chip").some((el) => el.textContent?.includes("1 tool call")),
    ).toBe(true);
  });
});

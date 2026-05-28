import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DisabledPlaceholder } from "@/components/gating/DisabledPlaceholder";

describe("<DisabledPlaceholder>", () => {
  it("renders the reason text and lock icon", () => {
    render(<DisabledPlaceholder reason="AI generation disabled in ZERO tier" />);
    expect(screen.getByText(/AI generation disabled in ZERO tier/)).toBeInTheDocument();
    expect(screen.getByTestId("disabled-placeholder")).toBeInTheDocument();
  });

  it("omits the CTA link when none is provided", () => {
    render(<DisabledPlaceholder reason="locked" />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders the CTA as an anchor with the given href and label", () => {
    render(
      <DisabledPlaceholder
        reason="locked"
        cta={{ label: "Configure LLM", href: "/settings/llm" }}
      />,
    );
    const link = screen.getByRole("link", { name: "Configure LLM" });
    expect(link).toHaveAttribute("href", "/settings/llm");
  });
});

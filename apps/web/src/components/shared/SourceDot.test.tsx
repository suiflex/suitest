import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceDot } from "@/components/shared/SourceDot";

describe("<SourceDot>", () => {
  it("renders with status attribute", () => {
    render(<SourceDot status="pass" />);
    const dot = screen.getByTestId("source-dot");
    expect(dot).toHaveAttribute("data-status", "pass");
    expect(dot.className).toContain("bg-accent");
  });

  it("applies pulse animation when status=running", () => {
    render(<SourceDot status="running" />);
    expect(screen.getByTestId("source-dot").className).toContain("suitest-pulse");
  });

  it("exposes title as aria-label when provided", () => {
    render(<SourceDot status="fail" title="Last run failed" />);
    expect(screen.getByRole("img", { name: "Last run failed" })).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/shared/StatusBadge";

describe("<StatusBadge>", () => {
  it("renders the default label for each status", () => {
    render(<StatusBadge status="pass" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Pass");
  });

  it("uses the custom label when provided", () => {
    render(<StatusBadge status="fail" label="Failed: timeout" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent(
      "Failed: timeout",
    );
  });

  it("applies the color class matching the status", () => {
    render(<StatusBadge status="ai" />);
    const badge = screen.getByTestId("status-badge");
    expect(badge).toHaveAttribute("data-status", "ai");
    expect(badge.className).toContain("text-violet");
  });

  it("renders a dot by default and hides it when withDot=false", () => {
    const { rerender } = render(<StatusBadge status="warn" />);
    expect(screen.getByTestId("status-badge-dot")).toBeInTheDocument();
    rerender(<StatusBadge status="warn" withDot={false} />);
    expect(screen.queryByTestId("status-badge-dot")).toBeNull();
  });
});

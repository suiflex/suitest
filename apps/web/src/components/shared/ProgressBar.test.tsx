import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar } from "@/components/shared/ProgressBar";

describe("<ProgressBar>", () => {
  it("renders the fill width based on value", () => {
    render(<ProgressBar value={42} />);
    const fill = screen.getByTestId("progress-bar-fill");
    expect(fill.style.width).toBe("42%");
  });

  it("clamps values above 100", () => {
    render(<ProgressBar value={250} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByTestId("progress-bar-fill").style.width).toBe("100%");
  });

  it("clamps negative values to 0", () => {
    render(<ProgressBar value={-12} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("applies variant class on fill", () => {
    render(<ProgressBar value={50} variant="warn" />);
    expect(screen.getByTestId("progress-bar-fill").className).toContain("bg-amber");
  });

  it("renders label + percentage when label is provided", () => {
    render(<ProgressBar value={75} label="Checkout suite" />);
    expect(screen.getByText("Checkout suite")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
  });
});

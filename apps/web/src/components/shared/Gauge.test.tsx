import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Gauge, SmallGauge } from "@/components/shared/Gauge";
import { gaugeColorClass } from "@/components/shared/gauge-utils";

describe("gaugeColorClass", () => {
  it.each([
    [85, "text-accent"],
    [80, "text-accent"],
    [79, "text-amber"],
    [60, "text-amber"],
    [59, "text-red"],
    [0, "text-red"],
    [-5, "text-red"],
    [120, "text-accent"],
  ] as const)("value=%i → %s", (value, expected) => {
    expect(gaugeColorClass(value)).toBe(expected);
  });
});

describe("<Gauge>", () => {
  it("renders the rounded value in the center", () => {
    render(<Gauge value={85} label="ready" />);
    const gauge = screen.getByTestId("gauge");
    expect(gauge).toHaveAttribute("data-value", "85");
    expect(gauge).toHaveTextContent("85");
    expect(gauge).toHaveTextContent("ready");
  });

  it("applies accent color class at value=85", () => {
    render(<Gauge value={85} />);
    const svg = screen.getByTestId("gauge").querySelector("svg");
    expect(svg?.getAttribute("class") ?? "").toContain("text-accent");
  });

  it("applies amber color at value=65", () => {
    render(<Gauge value={65} />);
    const svg = screen.getByTestId("gauge").querySelector("svg");
    expect(svg?.getAttribute("class") ?? "").toContain("text-amber");
  });

  it("applies red color at value=35", () => {
    render(<Gauge value={35} />);
    const svg = screen.getByTestId("gauge").querySelector("svg");
    expect(svg?.getAttribute("class") ?? "").toContain("text-red");
  });
});

describe("<SmallGauge>", () => {
  it("renders with 90px wrapper and value", () => {
    render(<SmallGauge value={50} />);
    const gauge = screen.getByTestId("small-gauge");
    expect(gauge).toHaveAttribute("data-value", "50");
    expect((gauge as HTMLElement).style.width).toBe("90px");
  });
});

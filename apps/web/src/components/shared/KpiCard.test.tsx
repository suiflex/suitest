import { render, screen } from "@testing-library/react";
import { Activity } from "lucide-react";
import { describe, expect, it } from "vitest";

import { KpiCard } from "@/components/shared/KpiCard";

describe("<KpiCard>", () => {
  it("renders label and value", () => {
    render(<KpiCard label="Pass rate" value="92%" />);
    expect(screen.getByTestId("kpi-card-label")).toHaveTextContent("Pass rate");
    expect(screen.getByTestId("kpi-card-value")).toHaveTextContent("92%");
  });

  it("renders delta with up direction → accent class", () => {
    render(
      <KpiCard label="Pass rate" value="92%" delta="+3%" deltaDirection="up" />,
    );
    const delta = screen.getByTestId("kpi-card-delta");
    expect(delta).toHaveTextContent("+3%");
    expect(delta).toHaveAttribute("data-delta-direction", "up");
    expect(delta.className).toContain("text-accent");
  });

  it("renders delta with down direction → red class", () => {
    render(
      <KpiCard label="Pass rate" value="92%" delta="-2%" deltaDirection="down" />,
    );
    const delta = screen.getByTestId("kpi-card-delta");
    expect(delta.className).toContain("text-red");
  });

  it("renders icon when provided", () => {
    const { container } = render(
      <KpiCard label="Active" value="3" icon={Activity} />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("omits delta row when delta is not provided", () => {
    render(<KpiCard label="Tests" value="100" />);
    expect(screen.queryByTestId("kpi-card-delta")).toBeNull();
  });
});

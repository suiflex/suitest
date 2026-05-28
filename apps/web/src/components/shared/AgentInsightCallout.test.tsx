import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";

describe("<AgentInsightCallout>", () => {
  it("renders title + body", () => {
    render(<AgentInsightCallout title="Likely flake" body="Retried 3×" />);
    expect(screen.getByTestId("agent-insight")).toHaveTextContent("Likely flake");
    expect(screen.getByTestId("agent-insight")).toHaveTextContent("Retried 3×");
  });

  it("hides the confidence pill when not provided", () => {
    render(<AgentInsightCallout title="t" body="b" />);
    expect(screen.queryByTestId("agent-insight-confidence")).toBeNull();
  });

  it("renders confidence pill with mapped class", () => {
    render(<AgentInsightCallout title="t" body="b" confidence="High" />);
    const pill = screen.getByTestId("agent-insight-confidence");
    expect(pill).toHaveTextContent("High");
    expect(pill.className).toContain("text-accent");
  });
});

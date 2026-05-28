import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { Button } from "@/components/ui/button";

describe("<DisabledTooltip>", () => {
  it("wraps children in an aria-disabled span with pointer-events disabled", () => {
    render(
      <DisabledTooltip reason="LLM not configured">
        <Button disabled>Generate (AI)</Button>
      </DisabledTooltip>,
    );
    const wrapper = screen.getByTestId("disabled-tooltip-wrapper");
    expect(wrapper).toHaveAttribute("aria-disabled", "true");
    expect(wrapper.className).toContain("pointer-events-none");
    expect(wrapper).toHaveAttribute("tabIndex", "0");
  });

  it("shows the reason text on hover", async () => {
    render(
      <DisabledTooltip reason="LLM not configured. Settings → LLM">
        <Button disabled>Generate</Button>
      </DisabledTooltip>,
    );
    await userEvent.hover(screen.getByTestId("disabled-tooltip-wrapper"));
    await waitFor(() => {
      // Radix portals the tooltip; assert on text content rather than parent.
      expect(
        screen.getAllByText("LLM not configured. Settings → LLM").length,
      ).toBeGreaterThan(0);
    });
  });
});

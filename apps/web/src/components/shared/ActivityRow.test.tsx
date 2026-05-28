import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sparkles } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ActivityRow } from "@/components/shared/ActivityRow";

describe("<ActivityRow>", () => {
  it("renders text, time and tone attribute", () => {
    render(
      <ActivityRow icon={Sparkles} tone="violet" text="Agent suggested fix" time="2m ago" />,
    );
    const row = screen.getByTestId("activity-row");
    expect(row).toHaveAttribute("data-tone", "violet");
    expect(row).toHaveTextContent("Agent suggested fix");
    expect(row).toHaveTextContent("2m ago");
  });

  it("invokes action click handlers", async () => {
    const onClick = vi.fn();
    render(
      <ActivityRow
        icon={Sparkles}
        tone="accent"
        text="Run passed"
        time="1m"
        actions={
          <button type="button" onClick={onClick}>
            View
          </button>
        }
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "View" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { LlmStatusBadge } from "@/components/shared/LlmStatusBadge";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";
import { CLOUD_CAPS, ZERO_CAPS } from "@/test/capabilities";

function setCaps(capabilities: Capabilities | null): void {
  act(() => useCapabilities.setState({ capabilities, loading: false, error: null }));
}

describe("<LlmStatusBadge>", () => {
  afterEach(() => setCaps(null));

  it("shows that an LLM is not connected", () => {
    setCaps(ZERO_CAPS);
    render(<LlmStatusBadge />);
    expect(screen.getByTestId("llm-status-badge")).toHaveAttribute(
      "data-llm-status",
      "not_configured",
    );
  });

  it("shows the validated provider and model", async () => {
    setCaps(CLOUD_CAPS);
    render(<LlmStatusBadge />);
    const badge = screen.getByTestId("llm-status-badge");
    expect(badge).toHaveTextContent("Anthropic:claude-opus-4-7");
    await userEvent.click(badge);
    expect(await screen.findByTestId("llm-status-badge-popover")).toHaveTextContent("LLM ready");
  });
});

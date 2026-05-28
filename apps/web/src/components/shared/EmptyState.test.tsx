import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Inbox } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "@/components/shared/EmptyState";

describe("<EmptyState>", () => {
  it("renders title and subtitle", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="No defects"
        subtitle="Suite kamu lagi clean."
      />,
    );
    expect(screen.getByText("No defects")).toBeInTheDocument();
    expect(screen.getByText("Suite kamu lagi clean.")).toBeInTheDocument();
  });

  it("invokes the CTA onClick handler", async () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        icon={Inbox}
        title="No runs"
        action={{ label: "Run now", onClick }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders an anchor when href is provided instead of onClick", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="No cases"
        action={{ label: "Generate from OpenAPI", href: "/cases/new" }}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Generate from OpenAPI" }),
    ).toHaveAttribute("href", "/cases/new");
  });

  it("renders multiple CTAs from an array", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="No cases yet"
        action={[
          { label: "Generate from OpenAPI", href: "/openapi" },
          { label: "Record" },
          { label: "Write manually" },
        ]}
      />,
    );
    const actions = screen.getByTestId("empty-state-actions");
    expect(actions.children).toHaveLength(3);
  });

  it("omits the action row when no action is provided", () => {
    render(<EmptyState icon={Inbox} title="Nothing here" />);
    expect(screen.queryByTestId("empty-state-actions")).toBeNull();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { VariableBadge } from "./VariableBadge";

describe("<VariableBadge>", () => {
  it("renders variable key formatted in double braces", () => {
    render(<VariableBadge variableKey="base_url" />);
    expect(screen.getByText("{{base_url}}")).toBeInTheDocument();
  });

  it("indicates secret variables with lock icon and masked preview", async () => {
    const user = userEvent.setup();
    render(
      <VariableBadge
        variableKey="api_token"
        isSecret={true}
        scope="workspace"
      />
    );

    expect(screen.getByText("{{api_token}}")).toBeInTheDocument();

    // Hover over badge to trigger tooltip
    const trigger = screen.getByText("{{api_token}}");
    await user.hover(trigger);

    const masks = await screen.findAllByText("••••••••");
    expect(masks.length).toBeGreaterThan(0);
    const scopeLabels = await screen.findAllByText("Workspace Default");
    expect(scopeLabels.length).toBeGreaterThan(0);
  });

  it("displays preview value for non-secret variables on hover", async () => {
    const user = userEvent.setup();
    render(
      <VariableBadge
        variableKey="app_env"
        value="staging"
        scope="suite"
        description="Suite staging environment"
      />
    );

    const trigger = screen.getByText("{{app_env}}");
    await user.hover(trigger);

    const values = await screen.findAllByText("staging");
    expect(values.length).toBeGreaterThan(0);
    const scopeLabels = await screen.findAllByText("Suite Override");
    expect(scopeLabels.length).toBeGreaterThan(0);
    const descs = await screen.findAllByText("Suite staging environment");
    expect(descs.length).toBeGreaterThan(0);
  });

  it("displays all scenarios breakdown when allRowValues is provided", async () => {
    const user = userEvent.setup();
    render(
      <VariableBadge
        variableKey="username"
        value="user"
        scope="dataset"
        allRowValues={[
          { rowName: "Default (Single Run)", value: "user" },
          { rowName: "Dataset Matrix #2", value: "superadministrator" },
        ]}
      />
    );

    const trigger = screen.getByText("{{username}}");
    await user.hover(trigger);

    const headers = await screen.findAllByText("All Scenarios (2)");
    expect(headers.length).toBeGreaterThan(0);
    const ddtBadges = await screen.findAllByText("DDT Matrix");
    expect(ddtBadges.length).toBeGreaterThan(0);
    const row1Labels = await screen.findAllByText("Default (Single Run):");
    expect(row1Labels.length).toBeGreaterThan(0);
    const row2Labels = await screen.findAllByText("Dataset Matrix #2:");
    expect(row2Labels.length).toBeGreaterThan(0);
    const superAdminValues = await screen.findAllByText("superadministrator");
    expect(superAdminValues.length).toBeGreaterThan(0);
  });
});

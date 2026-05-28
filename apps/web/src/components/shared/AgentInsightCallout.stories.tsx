import type { Meta, StoryObj } from "@storybook/react-vite";

import { AgentInsightCallout } from "./AgentInsightCallout";

const meta: Meta<typeof AgentInsightCallout> = {
  title: "Shared/AgentInsightCallout",
  component: AgentInsightCallout,
};

export default meta;

export const Default: StoryObj<typeof AgentInsightCallout> = {
  args: {
    title: "Likely flake on checkout suite",
    body: "Two retries in last 5 runs. Same selector, different network conditions.",
    confidence: "Medium",
  },
};

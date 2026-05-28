import type { Meta, StoryObj } from "@storybook/react-vite";

import { CostChip } from "./CostChip";

const meta: Meta<typeof CostChip> = {
  title: "Shared/CostChip",
  component: CostChip,
};

export default meta;

export const Default: StoryObj<typeof CostChip> = {
  args: { tokens: 4231, cost: 0.0184, provider: "anthropic", toolCalls: 7 },
};

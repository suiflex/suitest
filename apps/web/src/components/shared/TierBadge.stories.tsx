import type { Meta, StoryObj } from "@storybook/react-vite";

import { TierBadge } from "./TierBadge";

const meta: Meta<typeof TierBadge> = {
  title: "Shared/TierBadge",
  component: TierBadge,
};

export default meta;

export const Default: StoryObj<typeof TierBadge> = {};

export const Zero: StoryObj<typeof TierBadge> = {
  parameters: { capabilities: "ZERO" },
};

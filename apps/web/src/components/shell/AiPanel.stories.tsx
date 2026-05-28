import type { Meta, StoryObj } from "@storybook/react-vite";

import { AiPanel } from "./AiPanel";

const meta: Meta<typeof AiPanel> = {
  title: "Shell/AiPanel",
  component: AiPanel,
};

export default meta;

/**
 * CLOUD tier — full agent panel placeholder visible.
 */
export const CloudAssist: StoryObj<typeof AiPanel> = {
  parameters: { capabilities: "CLOUD" },
};

/**
 * ZERO tier — gated to null. The `<Gated>` wrapper renders no children, so
 * the right rail collapses in the live shell.
 */
export const HiddenInZero: StoryObj<typeof AiPanel> = {
  parameters: { capabilities: "ZERO" },
};

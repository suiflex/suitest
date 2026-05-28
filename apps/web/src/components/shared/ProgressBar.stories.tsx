import type { Meta, StoryObj } from "@storybook/react-vite";

import { ProgressBar } from "./ProgressBar";

const meta: Meta<typeof ProgressBar> = {
  title: "Shared/ProgressBar",
  component: ProgressBar,
};

export default meta;

export const Default: StoryObj<typeof ProgressBar> = {
  args: { value: 64, label: "Coverage" },
};

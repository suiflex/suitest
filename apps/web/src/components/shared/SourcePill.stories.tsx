import type { Meta, StoryObj } from "@storybook/react-vite";

import { SourcePill } from "./SourcePill";

const meta: Meta<typeof SourcePill> = {
  title: "Shared/SourcePill",
  component: SourcePill,
};

export default meta;

export const Default: StoryObj<typeof SourcePill> = {
  args: { source: "MANUAL" },
};

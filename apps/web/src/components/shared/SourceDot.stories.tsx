import type { Meta, StoryObj } from "@storybook/react-vite";

import { SourceDot } from "./SourceDot";

const meta: Meta<typeof SourceDot> = {
  title: "Shared/SourceDot",
  component: SourceDot,
};

export default meta;

export const Default: StoryObj<typeof SourceDot> = {
  args: { status: "pass", title: "Last run passed" },
};

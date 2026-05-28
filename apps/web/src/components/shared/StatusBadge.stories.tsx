import type { Meta, StoryObj } from "@storybook/react-vite";

import { StatusBadge } from "./StatusBadge";

const meta: Meta<typeof StatusBadge> = {
  title: "Shared/StatusBadge",
  component: StatusBadge,
};

export default meta;

export const Default: StoryObj<typeof StatusBadge> = {
  args: { status: "pass", label: "Passing" },
};

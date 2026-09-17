import type { Meta, StoryObj } from "@storybook/react-vite";

import { LlmStatusBadge } from "./LlmStatusBadge";

const meta: Meta<typeof LlmStatusBadge> = {
  title: "Shared/LlmStatusBadge",
  component: LlmStatusBadge,
};

export default meta;
export const Default: StoryObj<typeof LlmStatusBadge> = {};

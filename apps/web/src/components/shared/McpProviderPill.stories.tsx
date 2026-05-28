import type { Meta, StoryObj } from "@storybook/react-vite";

import { McpProviderPill } from "./McpProviderPill";

const meta: Meta<typeof McpProviderPill> = {
  title: "Shared/McpProviderPill",
  component: McpProviderPill,
};

export default meta;

export const Default: StoryObj<typeof McpProviderPill> = {
  args: { provider: { name: "playwright-mcp", health: "healthy", transport: "stdio" } },
};

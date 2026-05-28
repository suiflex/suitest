import type { Meta, StoryObj } from "@storybook/react-vite";

import { Sidebar } from "./Sidebar";

const meta: Meta<typeof Sidebar> = {
  title: "Shell/Sidebar",
  component: Sidebar,
};

export default meta;

export const Default: StoryObj<typeof Sidebar> = {};

export const ActiveOnRuns: StoryObj<typeof Sidebar> = {
  args: { activeRunsCount: 3 },
};

export const WithBadges: StoryObj<typeof Sidebar> = {
  args: { inboxCount: 7, unreadCount: 2, activeRunsCount: 1 },
};

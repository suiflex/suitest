import type { Meta, StoryObj } from "@storybook/react-vite";

import { Topbar } from "./Topbar";

const meta: Meta<typeof Topbar> = {
  title: "Shell/Topbar",
  component: Topbar,
};

export default meta;

export const Default: StoryObj<typeof Topbar> = {};

import type { Meta, StoryObj } from "@storybook/react-vite";

import { AutonomyIndicator } from "./AutonomyIndicator";

const meta: Meta<typeof AutonomyIndicator> = {
  title: "Shared/AutonomyIndicator",
  component: AutonomyIndicator,
};

export default meta;

export const Default: StoryObj<typeof AutonomyIndicator> = {};

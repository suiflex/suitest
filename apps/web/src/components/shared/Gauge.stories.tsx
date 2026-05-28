import type { Meta, StoryObj } from "@storybook/react-vite";

import { Gauge } from "./Gauge";

const meta: Meta<typeof Gauge> = {
  title: "Shared/Gauge",
  component: Gauge,
};

export default meta;

export const Default: StoryObj<typeof Gauge> = {
  args: { value: 72, label: "Score", sublabel: "Release readiness" },
};

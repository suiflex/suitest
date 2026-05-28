import { Sparkles } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { ActivityRow } from "./ActivityRow";

const meta: Meta<typeof ActivityRow> = {
  title: "Shared/ActivityRow",
  component: ActivityRow,
};

export default meta;

export const Default: StoryObj<typeof ActivityRow> = {
  args: {
    icon: Sparkles,
    tone: "violet",
    text: "Generated 12 test cases from openapi.json",
    time: "2m ago",
  },
};

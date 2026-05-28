import { Check } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { KpiCard } from "./KpiCard";

const meta: Meta<typeof KpiCard> = {
  title: "Shared/KpiCard",
  component: KpiCard,
};

export default meta;

export const Default: StoryObj<typeof KpiCard> = {
  args: { label: "Pass rate", value: "94%", icon: Check, delta: "+2.1pp", deltaDirection: "up" },
};

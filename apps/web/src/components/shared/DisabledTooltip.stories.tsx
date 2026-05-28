import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button } from "@/components/ui/button";

import { DisabledTooltip } from "./DisabledTooltip";

const meta: Meta<typeof DisabledTooltip> = {
  title: "Shared/DisabledTooltip",
  component: DisabledTooltip,
};

export default meta;

export const Default: StoryObj<typeof DisabledTooltip> = {
  args: {
    reason: "Authoring tools enabled in M1d",
    children: (
      <Button type="button" size="sm" disabled>
        + New
      </Button>
    ),
  },
};

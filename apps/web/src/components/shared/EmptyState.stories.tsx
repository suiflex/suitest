import { Inbox } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { EmptyState } from "./EmptyState";

const meta: Meta<typeof EmptyState> = {
  title: "Shared/EmptyState",
  component: EmptyState,
};

export default meta;

export const Default: StoryObj<typeof EmptyState> = {
  args: {
    icon: Inbox,
    title: "Nothing here yet",
    subtitle: "Mentions and review requests show up in this view.",
  },
};

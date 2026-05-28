import "../src/styles/globals.css";

import type { Preview } from "@storybook/react-vite";

import { withCapabilities } from "./decorators/capabilities";

/**
 * Global Storybook preview. Loads the same Tailwind 4 token sheet the app
 * boots with so component framing matches the live shell exactly.
 *
 * Per-story capability seeding is handled by `withCapabilities` — declare
 * `parameters.capabilities = "ZERO" | "LOCAL" | "CLOUD"` on a story to
 * override (default: CLOUD).
 */
const preview: Preview = {
  parameters: {
    backgrounds: {
      default: "dark",
      values: [{ name: "dark", value: "#0a0a0a" }],
    },
    layout: "fullscreen",
  },
  decorators: [withCapabilities],
};

export default preview;

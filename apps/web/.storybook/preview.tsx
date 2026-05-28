import "../src/styles/globals.css";

import type { Preview } from "@storybook/react-vite";

import { withCapabilities } from "./decorators/capabilities";
import { withRouter } from "./decorators/router";

/**
 * Global Storybook preview. Loads the same Tailwind 4 token sheet the app
 * boots with so component framing matches the live shell exactly.
 *
 * Per-story capability seeding is handled by `withCapabilities` — declare
 * `parameters.capabilities = "ZERO" | "LOCAL" | "CLOUD"` on a story to
 * override (default: CLOUD).
 *
 * `withRouter` wraps every story in a memory-history TanStack Router so
 * shell components (Sidebar/Topbar) that depend on `<Link>` / `useMatches`
 * / `useNavigate` render without crashing the Storybook canvas.
 */
const preview: Preview = {
  parameters: {
    backgrounds: {
      default: "dark",
      values: [{ name: "dark", value: "#0a0a0a" }],
    },
    layout: "fullscreen",
  },
  decorators: [withRouter, withCapabilities],
};

export default preview;

import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  // Storybook 10 bundles essentials into core; we keep the addons list lean.
  addons: [],
  framework: { name: "@storybook/react-vite", options: {} },
  typescript: { reactDocgen: false },
};

export default config;

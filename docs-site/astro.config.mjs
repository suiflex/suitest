import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// M4-14: Suitest site — custom landing at `/`, Starlight docs under `/docs/*`.
export default defineConfig({
  site: "https://suitest.suiflex.dev",
  integrations: [
    starlight({
      title: "Suitest",
      description: "MCP-native testing platform — manual TCM, deterministic runs, optional AI.",
      logo: {
        light: "./src/assets/logo-light.svg",
        dark: "./src/assets/logo-dark.svg",
        replacesTitle: true,
      },
      favicon: "/favicon.svg",
      social: { github: "https://github.com/suiflex/suitest" },
      sidebar: [
        { label: "Start here", items: [
          { label: "Introduction", link: "/docs/" },
          { label: "Getting started", link: "/docs/guides/getting-started/" },
          { label: "Tutorial: first run", link: "/docs/guides/tutorial/" },
        ]},
        { label: "Reference", items: [
          { label: "Capability tiers", link: "/docs/reference/tiers/" },
          { label: "API reference", link: "/docs/reference/api/" },
          { label: "CLI", link: "/docs/reference/cli/" },
        ]},
      ],
    }),
  ],
});

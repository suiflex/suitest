import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// M4-14: Suitest documentation site (Astro Starlight).
export default defineConfig({
  site: "https://docs.suitest.dev",
  integrations: [
    starlight({
      title: "Suitest",
      description: "MCP-native testing platform — manual TCM, deterministic runs, optional AI.",
      social: { github: "https://github.com/suitest-dev/suitest" },
      sidebar: [
        { label: "Start here", items: [
          { label: "Introduction", link: "/" },
          { label: "Getting started", link: "/guides/getting-started/" },
          { label: "Tutorial: first run", link: "/guides/tutorial/" },
        ]},
        { label: "Reference", items: [
          { label: "Capability tiers", link: "/reference/tiers/" },
          { label: "API reference", link: "/reference/api/" },
          { label: "CLI", link: "/reference/cli/" },
        ]},
      ],
    }),
  ],
});

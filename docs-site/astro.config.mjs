import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// Suitest site: custom landing at `/`, Starlight docs under `/docs/*`.
export default defineConfig({
  site: "https://suitest.suiflex.dev",
  integrations: [
    starlight({
      title: "Suitest",
      description:
        "Documentation for Suitest, the open-source MCP-native testing platform: install, agent workflow, CI, and full CLI, config, and API references.",
      logo: {
        light: "./src/assets/logo-light.svg",
        dark: "./src/assets/logo-dark.svg",
        replacesTitle: true,
      },
      favicon: "/favicon.svg",
      social: { github: "https://github.com/suiflex/suitest" },
      editLink: {
        baseUrl: "https://github.com/suiflex/suitest/edit/main/docs-site/",
      },
      lastUpdated: true,
      head: [
        {
          tag: "meta",
          attrs: { property: "og:image", content: "https://suitest.suiflex.dev/og.png" },
        },
        {
          tag: "meta",
          attrs: { name: "twitter:card", content: "summary_large_image" },
        },
      ],
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "Introduction", link: "/docs/" },
            { label: "Getting started", link: "/docs/guides/getting-started/" },
            { label: "Tutorial: first run", link: "/docs/guides/tutorial/" },
          ],
        },
        {
          label: "Installation",
          items: [
            { label: "Local bundle (one command)", link: "/docs/install/local-bundle/" },
            { label: "MCP server (IDE agents)", link: "/docs/install/mcp-server/" },
            { label: "Docker Compose", link: "/docs/install/docker/" },
            { label: "Kubernetes (Helm)", link: "/docs/install/kubernetes/" },
            { label: "From source", link: "/docs/install/from-source/" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "How Suitest works", link: "/docs/concepts/how-it-works/" },
            { label: "Projects, cases, and runs", link: "/docs/concepts/data-model/" },
            { label: "Evidence and artifacts", link: "/docs/concepts/evidence/" },
            { label: "Capability tiers", link: "/docs/reference/tiers/" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "Testing from your IDE agent", link: "/docs/guides/agent-workflow/" },
            { label: "Blackbox testing from a URL", link: "/docs/guides/blackbox-testing/" },
            { label: "The failure bundle", link: "/docs/guides/failure-context/" },
            { label: "Bring your own LLM", link: "/docs/guides/llm-setup/" },
            { label: "CI with the GitHub Action", link: "/docs/guides/ci-github-action/" },
            { label: "Self-hosting in production", link: "/docs/guides/self-hosting/" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "MCP tools", link: "/docs/reference/mcp-tools/" },
            { label: "CLI", link: "/docs/reference/cli/" },
            { label: "suitest.config.json", link: "/docs/reference/configuration/" },
            { label: "REST API", link: "/docs/reference/api/" },
            { label: "Environment variables", link: "/docs/reference/environment/" },
          ],
        },
        {
          label: "Help",
          items: [
            { label: "Troubleshooting", link: "/docs/help/troubleshooting/" },
            { label: "FAQ", link: "/docs/help/faq/" },
          ],
        },
      ],
    }),
  ],
});

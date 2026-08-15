// Build the docs-site "Release notes" page from the package CHANGELOGs.
//
// release-please already owns the changelogs (it writes them on every release
// PR), so the docs must not keep a second hand-written copy — that copy is what
// goes stale. This script is the only place the two are joined, and it runs
// from `predev` / `prebuild`, so every dev server and every deploy regenerates
// the page. Updating the site after a release is therefore: nothing.
//
// Run manually: node scripts/sync-changelog.mjs

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const out = resolve(here, "..", "src/content/docs/docs/changelog.md");

// Order = what a reader installs first. `npm` name is what the badge/link uses.
const PACKAGES = [
  {
    dir: "packages/suitest-npx",
    title: "Local bundle — `@suiflex/suitest`",
    npm: "@suiflex/suitest",
    tag: "launcher",
    blurb: "The one-command local platform (`npx @suiflex/suitest onboard`). Ships the web dashboard and every Python wheel, so an API or renderer change reaches you through this package.",
  },
  {
    dir: "packages/mcp-npx",
    title: "MCP server — `@suiflex/suitest-mcp`",
    npm: "@suiflex/suitest-mcp",
    tag: "mcp",
    blurb: "The MCP server your IDE agent talks to, and the lifecycle engine that generates and runs tests. Published to npm and to PyPI as `suiflex-suitest-lifecycle`.",
  },
];

/** Drop the `# Changelog` title and demote every heading one level below ours. */
function body(markdown) {
  return markdown
    .replace(/^#\s+Changelog\s*/, "")
    .trim()
    .replace(/^(#{2,5})\s/gm, "#$1 ");
}

const sections = PACKAGES.map((pkg) => {
  const version = JSON.parse(
    readFileSync(resolve(repo, pkg.dir, "package.json"), "utf8"),
  ).version;
  const changelog = body(readFileSync(resolve(repo, pkg.dir, "CHANGELOG.md"), "utf8"));
  return `## ${pkg.title}

Current: **${version}** · [npm](https://www.npmjs.com/package/${pkg.npm}) · [releases](https://github.com/suiflex/suitest/releases?q=${pkg.tag}-v)

${pkg.blurb}

${changelog}`;
});

const page = `---
title: Release notes
description: Every released version of the Suitest local bundle and MCP server, with the changes in each — generated from the package changelogs.
editUrl: false
---

:::tip[Which package do I update?]
A change to the API, the web dashboard, or the UAT export reaches you through the
**local bundle** (\`npx @suiflex/suitest@latest onboard\`). A change to test
generation, test execution, or the IDE tools reaches you through the **MCP
server** (\`npx -y @suiflex/suitest-mcp@latest\`). Bumping one does not bump the
other.
:::

${sections.join("\n\n")}

---

*This page is generated from \`packages/*/CHANGELOG.md\` by
\`docs-site/scripts/sync-changelog.mjs\` on every build. Edit the changelogs (or
let release-please write them), not this page.*
`;

writeFileSync(out, page);
console.log(`sync-changelog: wrote ${out}`);

/**
 * Command strings for the Connect-IDE dialog, kept out of the component file so
 * they can be unit-tested and imported without tripping react-refresh's
 * "only export components" rule.
 */
export const NPM_PKG = "@suiflex/suitest-mcp";
export const SERVER_CMD = `npx -y ${NPM_PKG}`;
export const START_PROMPT = "Hey, generate and run tests for this project with Suitest.";
export const KEY_PLACEHOLDER = "<your-api-key>";

/** Tab id → the installer's `--client` target (matches the npx installer). */
export const IDE_CLIENTS = {
  claude: "claude-code",
  cursor: "cursor",
  windsurf: "windsurf",
} as const;
export type IdeTab = keyof typeof IDE_CLIENTS;

export function apiUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) return window.location.origin;
  return "http://localhost:4000";
}

/** One-command install: the npx installer writes the IDE's MCP config for you. */
export function installCmd(client: string): string {
  return `npx -y ${NPM_PKG} install --client ${client}`;
}

export function claudeCmd(): string {
  return [
    "claude mcp add suitest \\",
    `  --env SUITEST_API_KEY=${KEY_PLACEHOLDER} \\`,
    `  --env SUITEST_API_URL=${apiUrl()} \\`,
    `  -- npx -y ${NPM_PKG}`,
  ].join("\n");
}

export function mcpJson(): string {
  return `{
  "mcpServers": {
    "suitest": {
      "command": "npx",
      "args": ["-y", "${NPM_PKG}"],
      "env": {
        "SUITEST_API_KEY": "${KEY_PLACEHOLDER}",
        "SUITEST_API_URL": "${apiUrl()}"
      }
    }
  }
}`;
}

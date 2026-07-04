import { Link } from "@tanstack/react-router";
import { AlertTriangle, Cpu, KeyRound } from "lucide-react";
import { useState } from "react";

import { CopyButton } from "@/components/shared/CopyButton";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

/**
 * "Connect Suitest to your AI IDE" — the outward MCP setup flow (Cursor /
 * Claude Code / any MCP-capable agent). Key creation lives in Settings → API
 * Keys (a key is a persistent, workspace-scoped credential); this dialog is a
 * copy-paste wiring guide that references the key by placeholder.
 */

const SERVER_CMD = "python -m suitest_lifecycle.mcp_server";
const START_PROMPT = "Hey, generate and run tests for this project with Suitest.";
const KEY_PLACEHOLDER = "<your-api-key>";

/** The lifecycle tools the connected agent can call. */
const TOOLS = [
  "analyze_project",
  "generate_test_cases",
  "generate_backend_tests",
  "generate_frontend_tests",
  "run_backend_tests",
  "run_frontend_tests",
  "run_tests",
  "generate_report",
  "runs",
] as const;

function apiUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) return window.location.origin;
  return "http://localhost:4000";
}

function claudeCmd(): string {
  return [
    "claude mcp add suitest \\",
    `  --env SUITEST_API_KEY=${KEY_PLACEHOLDER} \\`,
    `  --env SUITEST_API_URL=${apiUrl()} \\`,
    "  -- python -m suitest_lifecycle.mcp_server",
  ].join("\n");
}

function mcpJson(): string {
  return `{
  "mcpServers": {
    "suitest": {
      "command": "python",
      "args": ["-m", "suitest_lifecycle.mcp_server"],
      "env": {
        "SUITEST_API_KEY": "${KEY_PLACEHOLDER}",
        "SUITEST_API_URL": "${apiUrl()}"
      }
    }
  }
}`;
}

function CodeBlock({ code }: { code: string }): React.ReactElement {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border border-border bg-bg-code p-3 pr-11 font-mono text-[11.5px] leading-relaxed text-fg-2">
        <code>{code}</code>
      </pre>
      <div className="absolute top-2 right-2">
        <CopyButton value={code} label="Copy to clipboard" />
      </div>
    </div>
  );
}

function StepShell({
  n,
  title,
  aside,
  children,
}: {
  n: number;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <section className="rounded-lg border border-border bg-bg-elev-1 p-4">
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-bg-elev-3 font-mono text-[11px] font-semibold text-fg-2">
            {n}
          </span>
          <h3 className="text-[13px] font-semibold text-fg-1">{title}</h3>
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function ConnectIdeDialog(): React.ReactElement {
  const [open, setOpen] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="default" data-testid="connect-ide-trigger">
          <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
          Connect IDE
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[88vh] gap-0 overflow-y-auto p-0 sm:max-w-[560px]">
        <DialogHeader className="border-b border-border-subtle px-6 pt-6 pb-4">
          <DialogTitle className="text-[16px]">Connect Suitest to your AI IDE</DialogTitle>
          <DialogDescription className="text-[12.5px]">
            Point Cursor, Claude Code, or any MCP-capable agent at Suitest, then ask it to generate
            and run tests.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 px-6 py-5">
          <div className="rounded-lg border border-border bg-bg-elev-1 p-4">
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-[13px] font-semibold text-fg-1">Suitest API endpoint</h3>
              <span className="font-mono text-[10.5px] text-fg-5">SUITEST_API_URL</span>
            </div>
            <p className="mb-2 text-[12px] text-fg-3">
              This self-hosted instance. Your IDE / SDK points here (each install differs).
            </p>
            <div className="relative">
              <div className="overflow-x-auto rounded-md border border-border bg-bg-code px-3 py-2 pr-11 font-mono text-[12px] text-fg-1">
                {apiUrl()}
              </div>
              <div className="absolute top-1.5 right-2">
                <CopyButton value={apiUrl()} label="Copy endpoint URL" />
              </div>
            </div>
          </div>

          <StepShell
            n={1}
            title="Get an API key"
            aside={
              <Link
                to="/settings"
                onClick={() => {
                  setOpen(false);
                }}
                className="text-[12px] font-medium text-accent hover:underline"
                data-testid="connect-ide-open-settings"
              >
                Settings → API Keys
              </Link>
            }
          >
            <p className="flex items-start gap-2 text-[12px] text-fg-3">
              <KeyRound className="mt-[1px] h-3.5 w-3.5 shrink-0 text-fg-4" aria-hidden="true" />
              Create and manage workspace keys in{" "}
              <span className="text-fg-2">Settings → API Keys</span>. Copy a key and drop it into
              the config below in place of{" "}
              <code className="rounded bg-bg-elev-2 px-1 font-mono text-[11px]">
                {KEY_PLACEHOLDER}
              </code>
              .
            </p>
          </StepShell>

          <StepShell n={2} title="Run the Suitest MCP server">
            <p className="mb-2 text-[12px] text-fg-3">
              Local stdio server exposing the lifecycle tools — ships with the{" "}
              <code className="rounded bg-bg-elev-2 px-1 font-mono text-[11px]">
                suiflex-suitest-lifecycle
              </code>{" "}
              package.
            </p>
            <CodeBlock code={SERVER_CMD} />
            <div className="mt-2 flex items-start gap-1.5 rounded-md border border-amber/25 bg-amber/[0.06] px-2.5 py-2 text-[11.5px] text-amber">
              <AlertTriangle className="mt-[1px] h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="text-fg-2">
                The <code className="font-mono text-[11px] text-fg-1">command</code> must be a
                Python that has{" "}
                <code className="font-mono text-[11px] text-fg-1">suiflex-suitest-lifecycle</code>{" "}
                installed. Either{" "}
                <code className="font-mono text-[11px] text-fg-1">
                  pip install suiflex-suitest-lifecycle
                </code>
                , or point it at the Suitest repo&apos;s venv, e.g.{" "}
                <code className="font-mono text-[11px] text-fg-1">
                  /path/to/suitest/.venv/bin/python
                </code>{" "}
                — not bare <code className="font-mono text-[11px] text-fg-1">python</code>.
              </span>
            </div>
          </StepShell>

          <StepShell
            n={3}
            title="Add it to your IDE"
            aside={
              <a
                href="/docs/MCP-USAGE"
                className="text-[12px] font-medium text-accent hover:underline"
              >
                Docs
              </a>
            }
          >
            <Tabs defaultValue="claude">
              <TabsList className="mb-3">
                <TabsTrigger value="claude" data-testid="connect-ide-tab-claude">
                  Claude Code
                </TabsTrigger>
                <TabsTrigger value="cursor">Cursor</TabsTrigger>
                <TabsTrigger value="other">Other IDEs</TabsTrigger>
              </TabsList>

              <TabsContent value="claude">
                <p className="mb-2 text-[12px] text-fg-3">From your project directory, run:</p>
                <CodeBlock code={claudeCmd()} />
              </TabsContent>

              <TabsContent value="cursor">
                <p className="mb-2 text-[12px] text-fg-3">
                  Add to{" "}
                  <code className="rounded bg-bg-elev-2 px-1 font-mono text-[11px]">
                    ~/.cursor/mcp.json
                  </code>
                  :
                </p>
                <CodeBlock code={mcpJson()} />
              </TabsContent>

              <TabsContent value="other">
                <p className="mb-2 text-[12px] text-fg-3">
                  Any MCP client accepts this server block:
                </p>
                <CodeBlock code={mcpJson()} />
              </TabsContent>
            </Tabs>
            <p className="mt-2 text-[11px] text-fg-4">
              Replace{" "}
              <code className="rounded bg-bg-elev-2 px-1 font-mono text-[10.5px]">
                {KEY_PLACEHOLDER}
              </code>{" "}
              with a key from Settings → API Keys.
            </p>
          </StepShell>

          <StepShell n={4} title="Start testing">
            <p className="mb-2 text-[12px] text-fg-3">
              Type this in your AI editor and it drives the rest:
            </p>
            <CodeBlock code={START_PROMPT} />
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] font-medium tracking-wide text-fg-4 uppercase">
                Tools the agent can call
              </p>
              <div className="flex flex-wrap gap-1.5">
                {TOOLS.map((t) => (
                  <span
                    key={t}
                    className="rounded-md border border-border-subtle bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10.5px] text-fg-3"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </StepShell>
        </div>

        <div className="border-t border-border-subtle px-6 py-4">
          <Button
            type="button"
            variant="default"
            className="w-full"
            onClick={() => {
              setOpen(false);
            }}
          >
            Got it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

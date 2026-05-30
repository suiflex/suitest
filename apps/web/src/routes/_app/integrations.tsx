import { createFileRoute } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, Plug } from "lucide-react";
import { Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { IntegrationsSkeleton } from "@/components/integrations/skeleton";
import { McpServersPanel } from "@/components/mcp/McpServersPanel";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { McpProviderPill } from "@/components/shared/McpProviderPill";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  useIntegrations,
  useMcpProviders,
  type McpProvider,
} from "@/hooks/use-integrations";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

type Integration = components["schemas"]["IntegrationListItem"];

type Tab = "all" | "cicd" | "issues" | "notifications" | "mcp" | "discovery";

const CATEGORY_OF: Record<Integration["kind"], Tab> = {
  GITHUB: "cicd",
  GITLAB: "cicd",
  JENKINS: "cicd",
  JIRA: "issues",
  LINEAR: "issues",
  SLACK: "notifications",
  OPENAPI: "discovery",
  MCP_BROWSER_USE: "mcp",
  MCP_PLAYWRIGHT: "mcp",
  MCP_CUSTOM: "mcp",
  MCP_API: "mcp",
  MCP_POSTGRES: "mcp",
  MCP_KUBERNETES: "mcp",
  MCP_GRAPHQL: "mcp",
  MCP_GRPC: "mcp",
  MCP_APPIUM: "mcp",
  MCP_MONGO: "mcp",
  MCP_MYSQL: "mcp",
};

function statusToBadge(status: string):
  | "pass"
  | "fail"
  | "warn"
  | "neutral" {
  const s = status.toLowerCase();
  if (s === "connected") return "pass";
  if (s === "disconnected") return "neutral";
  if (s === "error") return "fail";
  return "warn";
}

function categoryLabel(c: Tab): string {
  switch (c) {
    case "cicd":
      return "CI/CD";
    case "issues":
      return "Issue Tracker";
    case "notifications":
      return "Notifications";
    case "mcp":
      return "MCP";
    case "discovery":
      return "API Discovery";
    default:
      return "All";
  }
}

function IntegrationCard({
  item,
  onOpenMcp,
}: {
  item: Integration;
  onOpenMcp: () => void;
}): React.ReactElement {
  const category = CATEGORY_OF[item.kind];
  const status = statusToBadge(item.status);
  const isMcp = category === "mcp";
  return (
    <article
      data-testid="integration-card"
      data-kind={item.kind}
      className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-bg-elev-2 font-mono text-[11px] text-fg-3">
            {item.kind.slice(0, 2)}
          </div>
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold text-fg-1">{item.name}</span>
            <span className="font-mono text-[10.5px] text-fg-5">{categoryLabel(category)}</span>
          </div>
        </div>
        <StatusBadge status={status} label={item.status} />
      </div>
      <p className="text-[12.5px] text-fg-3">
        {item.kind} integration ({item.has_secrets ? "secrets stored" : "no secret material"}).
      </p>
      <footer className="flex items-center justify-between border-t border-border pt-2 font-mono text-[10.5px] text-fg-5">
        <span>
          {item.last_synced_at
            ? `Synced ${formatDistanceToNow(new Date(item.last_synced_at), { addSuffix: true })}`
            : "Never synced"}
        </span>
        {isMcp ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="integration-configure-mcp"
            onClick={onOpenMcp}
          >
            {item.status === "connected" ? "Configure" : "Connect"}
          </Button>
        ) : (
          <DisabledTooltip reason="Configuration ships in M2">
            <Button type="button" size="sm" variant="outline" disabled>
              {item.status === "connected" ? "Configure" : "Connect"}
            </Button>
          </DisabledTooltip>
        )}
      </footer>
    </article>
  );
}

function McpProviderCard({ provider }: { provider: McpProvider }): React.ReactElement {
  return (
    <article
      data-testid="mcp-card"
      data-provider-id={provider.id}
      className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <McpProviderPill
            provider={{
              name: provider.name,
              health: provider.health,
              transport: provider.transport,
            }}
          />
        </div>
        {provider.bundled ? (
          <span
            data-testid="mcp-bundled"
            className="rounded-full border border-border bg-bg-elev-2 px-2 py-0.5 font-mono text-[10px] text-fg-4"
          >
            BUNDLED
          </span>
        ) : null}
      </div>
      <p className="text-[12.5px] text-fg-3">
        <span className="font-mono text-[11px] text-fg-4">{provider.kind}</span> target. Last
        checked{" "}
        {provider.last_checked_at
          ? formatDistanceToNow(new Date(provider.last_checked_at), { addSuffix: true })
          : "never"}
        .
      </p>
      <footer className="flex items-center justify-between border-t border-border pt-2">
        <DisabledTooltip reason="Discovered tools list ships in M2">
          <Button type="button" size="sm" variant="ghost" disabled>
            Show discovered tools
          </Button>
        </DisabledTooltip>
        <DisabledTooltip reason="Test connection ships in M2">
          <Button type="button" size="sm" variant="outline" disabled>
            Test connection
          </Button>
        </DisabledTooltip>
      </footer>
    </article>
  );
}

function IntegrationsBody(): React.ReactElement {
  const { data: integrations } = useIntegrations();
  const { data: mcp } = useMcpProviders();
  const [active, setActive] = useState<Tab>("all");

  const counts = useMemo(() => {
    const c: Record<Tab, number> = {
      all: integrations.items.length + mcp.items.length,
      cicd: 0,
      issues: 0,
      notifications: 0,
      mcp: mcp.items.length,
      discovery: 0,
    };
    for (const it of integrations.items) {
      const cat = CATEGORY_OF[it.kind];
      c[cat] += 1;
    }
    return c;
  }, [integrations, mcp]);

  const showMcp = active === "all" || active === "mcp";
  // The dedicated MCP tab now uses the live `McpServersPanel` (M1c task 20).
  // The "All" tab keeps the legacy card grid so other categories still render
  // alongside the MCP summary without duplicating the panel.
  const showMcpPanel = active === "mcp";
  const showMcpGrid = active === "all";
  const filteredIntegrations = useMemo(() => {
    if (active === "all") return integrations.items;
    if (active === "mcp") return [] as Integration[];
    return integrations.items.filter((it) => CATEGORY_OF[it.kind] === active);
  }, [active, integrations]);

  const mcpHasItems = mcp.items.length > 0;
  const showEmpty = filteredIntegrations.length === 0 && (!showMcp || !mcpHasItems);

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "all", label: "All" },
    { id: "cicd", label: "CI/CD" },
    { id: "issues", label: "Issue Tracker" },
    { id: "notifications", label: "Notifications" },
    { id: "mcp", label: "MCP Servers" },
    { id: "discovery", label: "API Discovery" },
  ];

  return (
    <>
      <nav className="flex items-center gap-1 border-b border-border pb-2" data-testid="integrations-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={`integrations-tab-${t.id}`}
            data-active={active === t.id ? "true" : "false"}
            onClick={() => {
              setActive(t.id);
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-fg-3 hover:bg-bg-elev-2",
              active === t.id && "bg-bg-elev-2 text-fg-1",
            )}
          >
            {t.label}
            <span className="font-mono text-[10.5px] text-fg-5">{counts[t.id]}</span>
          </button>
        ))}
      </nav>

      {showEmpty ? (
        <EmptyState
          icon={Plug}
          title="No integrations in this category"
          subtitle="Add a Jira, GitHub, or Slack workspace to populate this tab."
        />
      ) : (
        <div className="flex flex-col gap-6">
          {filteredIntegrations.length > 0 && (
            <section className="grid grid-cols-3 gap-3" data-testid="integrations-grid">
              {filteredIntegrations.map((it) => (
                <IntegrationCard
                  key={it.id}
                  item={it}
                  onOpenMcp={() => {
                    setActive("mcp");
                  }}
                />
              ))}
            </section>
          )}
          {showMcpGrid && (
            <section className="flex flex-col gap-3" data-testid="mcp-section">
              <header className="flex items-center justify-between">
                <h3 className="text-[13px] font-semibold text-fg-1">MCP Servers</h3>
                <DisabledTooltip reason="Available in M2">
                  <Button type="button" size="sm" variant="outline" disabled>
                    Add Custom MCP
                  </Button>
                </DisabledTooltip>
              </header>
              <div className="grid grid-cols-3 gap-3" data-testid="mcp-grid">
                {mcp.items.map((p) => (
                  <McpProviderCard key={p.id} provider={p} />
                ))}
              </div>
            </section>
          )}
          {showMcpPanel && (
            <section className="flex flex-col gap-3" data-testid="mcp-section">
              <McpServersPanel />
            </section>
          )}
        </div>
      )}
    </>
  );
}

function IntegrationsError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load integrations"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Integrations(): React.ReactElement {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-4" data-testid="integrations-screen">
      <header>
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">{t("integrations.title")}</h2>
      </header>
      <ErrorBoundary fallback={({ reset }) => <IntegrationsError reset={reset} />}>
        <Suspense fallback={<IntegrationsSkeleton />}>
          <IntegrationsBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/integrations")({
  component: Integrations,
  staticData: { title: "Integrations" },
});

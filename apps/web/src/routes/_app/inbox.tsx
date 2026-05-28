import { createFileRoute } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  Bot,
  Inbox as InboxIcon,
  PlugZap,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Suspense } from "react";

import { Gated } from "@/components/gating/Gated";
import { InboxSkeleton } from "@/components/inbox/skeleton";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Button } from "@/components/ui/button";
import {
  isZeroSafeKind,
  useInbox,
  type InboxItem,
  type InboxItemKind,
} from "@/hooks/use-inbox";
import { useCapabilities } from "@/stores/use-capabilities";

const KIND_META: Record<InboxItemKind, { icon: LucideIcon; tone: string; label: string }> = {
  GATING_FAIL: { icon: ShieldAlert, tone: "text-red", label: "Gating" },
  FLAKY_PROMOTION: { icon: TriangleAlert, tone: "text-amber", label: "Flaky" },
  MANUAL_RUN_FAIL: { icon: AlertTriangle, tone: "text-red", label: "Run" },
  MCP_HEALTH: { icon: PlugZap, tone: "text-amber", label: "MCP" },
  AGENT_DEFECT_FILED: { icon: Sparkles, tone: "text-violet", label: "Agent" },
  AGENT_GENERATION_DONE: { icon: Bot, tone: "text-violet", label: "Agent" },
};

function NotificationCard({ item }: { item: InboxItem }): React.ReactElement {
  const meta = KIND_META[item.kind];
  const Icon = meta.icon;
  return (
    <article
      data-testid="inbox-card"
      data-kind={item.kind}
      data-read={item.read ? "true" : "false"}
      className="flex items-start gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <span
        className={`mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full bg-bg-elev-2 ${meta.tone}`}
        aria-hidden="true"
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold text-fg-1">{item.title}</h3>
          <span className="font-mono text-[10.5px] text-fg-5">
            {formatDistanceToNow(new Date(item.createdAt), { addSuffix: true })}
          </span>
        </div>
        <p className="text-[12.5px] text-fg-3">{item.body}</p>
        <div className="mt-1 flex items-center justify-between">
          <span className="font-mono text-[10.5px] text-fg-5">
            {meta.label}
            {item.ref ? ` · ${item.ref}` : ""}
          </span>
          <div className="flex items-center gap-1.5">
            <Button type="button" size="sm" variant="outline" disabled>
              Review
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled>
              Dismiss
            </Button>
          </div>
        </div>
      </div>
    </article>
  );
}

function InboxList(): React.ReactElement {
  const { data } = useInbox("all");
  const tier = useCapabilities((s) => s.capabilities?.tier);
  const visible = data.items.filter((item) => {
    if (tier === "ZERO") return isZeroSafeKind(item.kind);
    return true;
  });

  if (visible.length === 0) {
    return (
      <EmptyState
        icon={InboxIcon}
        title="Inbox is empty"
        subtitle="Nothing needs attention."
      />
    );
  }

  return (
    <div className="flex flex-col gap-[14px]" data-testid="inbox-list">
      {visible.map((item) => {
        if (item.kind === "AGENT_DEFECT_FILED" || item.kind === "AGENT_GENERATION_DONE") {
          return (
            <Gated key={item.id} feature="ai_panel" fallback={null}>
              <NotificationCard item={item} />
            </Gated>
          );
        }
        return <NotificationCard key={item.id} item={item} />;
      })}
    </div>
  );
}

function UnreadBadge(): React.ReactElement | null {
  const { data } = useInbox("all");
  if (data.unread === 0) return null;
  return (
    <span
      data-testid="inbox-unread"
      className="inline-flex items-center rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent"
    >
      {data.unread} unread
    </span>
  );
}

function InboxHeader(): React.ReactElement {
  return (
    <header className="flex items-center justify-between" data-testid="inbox-header">
      <div className="flex items-center gap-2.5">
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">Inbox</h2>
        <Suspense fallback={null}>
          <UnreadBadge />
        </Suspense>
      </div>
    </header>
  );
}

function InboxError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load inbox"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Inbox(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="inbox-screen">
      <ErrorBoundary fallback={({ reset }) => <InboxError reset={reset} />}>
        <InboxHeader />
        <Suspense fallback={<InboxSkeleton />}>
          <InboxList />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/inbox")({
  component: Inbox,
  staticData: { title: "Inbox" },
});

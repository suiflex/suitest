import { createFileRoute } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  Clock,
  ListChecks,
  Play,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { Suspense } from "react";

import { DashboardSkeleton } from "@/components/dashboard/skeleton";
import { PassRateChart } from "@/components/dashboard/PassRateChart";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Gauge } from "@/components/shared/Gauge";
import { KpiCard } from "@/components/shared/KpiCard";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  useAgentActivity,
  useDashboardCoverage,
  useDashboardKpis,
  useDashboardPassRate,
  useDashboardReadiness,
  useRecentRuns,
} from "@/hooks/use-dashboard";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const DASHBOARD_PERIOD = "7d";

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

function KpiSection(): React.ReactElement {
  const { data: kpis } = useDashboardKpis(DASHBOARD_PERIOD);
  const hasData = kpis.runCount > 0;
  const passPct = hasData ? `${Math.round(kpis.passRate * 100)}%` : "—";
  const runs = hasData ? kpis.runCount.toString() : "—";
  const avg = hasData ? formatDuration(kpis.avgDurationMs) : "—";
  const defects = hasData ? kpis.defectsOpen.toString() : "—";

  return (
    <div className="grid grid-cols-4 gap-[14px]" data-testid="dashboard-kpis">
      <KpiCard label="Tests run · 7d" value={runs} icon={Play} />
      <KpiCard label="Pass rate" value={passPct} icon={Check} />
      <KpiCard label="Avg duration" value={avg} icon={Clock} />
      <KpiCard label="Open defects" value={defects} icon={AlertTriangle} />
    </div>
  );
}

function PassRateCard(): React.ReactElement {
  const { data } = useDashboardPassRate("11d");
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="dashboard-pass-rate"
    >
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-fg-1">Pass rate</h3>
          <p className="text-[11.5px] text-fg-4">Daily, last 11 days</p>
        </div>
        <span className="font-mono text-[11px] text-fg-4">{data.total} runs</span>
      </header>
      <PassRateChart data={data} />
    </section>
  );
}

function CoverageCard(): React.ReactElement {
  const { data } = useDashboardCoverage();
  const suites = data.bySuite ?? [];
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="dashboard-coverage"
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-fg-1">Coverage by suite</h3>
        <span className="font-mono text-[11px] text-fg-4">{suites.length} suites</span>
      </header>
      {suites.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No suites yet"
          subtitle="Group cases into suites to see coverage rollups."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {suites.map((s) => (
            <li key={s.suiteId} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-fg-1">{s.name}</span>
                <span className="font-mono text-fg-4">
                  {s.covered}/{s.total}
                </span>
              </div>
              <ProgressBar value={s.coverage * 100} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type RunListItem = components["schemas"]["RunListItem"];

function runStatusToBadge(status: RunListItem["status"]):
  | "pass"
  | "fail"
  | "warn"
  | "running"
  | "neutral" {
  switch (status) {
    case "PASS":
      return "pass";
    case "FAIL":
    case "ERROR":
      return "fail";
    case "RUNNING":
      return "running";
    case "QUEUED":
      return "neutral";
    case "CANCELLED":
      return "warn";
    default:
      return "neutral";
  }
}

function RecentRunsCard(): React.ReactElement {
  const { data } = useRecentRuns(5);
  const runs = data.items.slice(0, 5);

  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="dashboard-recent-runs"
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-fg-1">Recent runs</h3>
        <span className="font-mono text-[11px] text-fg-4">{runs.length}</span>
      </header>
      {runs.length === 0 ? (
        <EmptyState
          icon={Play}
          title="No runs yet"
          subtitle="Trigger a manual or CI run to populate this list."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {runs.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between rounded-md px-2 py-1.5 text-[12.5px] hover:bg-bg-elev-2"
              data-testid="recent-run-row"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <StatusBadge status={runStatusToBadge(r.status)} />
                <span className="truncate text-fg-1">{r.name}</span>
              </div>
              <div className="flex items-center gap-3 font-mono text-[11px] text-fg-4">
                <span>
                  {r.branch ?? "—"}
                  {r.commit_sha ? `@${r.commit_sha.slice(0, 7)}` : ""}
                </span>
                <span>{formatDuration(r.duration_ms)}</span>
                <span>
                  {r.started_at
                    ? formatDistanceToNow(new Date(r.started_at), { addSuffix: true })
                    : "—"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentActivityCard(): React.ReactElement {
  const { data } = useAgentActivity(5);
  const items = data.items ?? [];
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="dashboard-agent-activity"
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-fg-1">Agent activity</h3>
        <Sparkles className="h-3.5 w-3.5 text-violet" aria-hidden="true" />
      </header>
      {items.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="Agent disabled"
          subtitle="Running in manual mode. AI features off."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((entry) => (
            <li key={entry.id} className="rounded-md px-2 py-1.5 text-[12.5px] hover:bg-bg-elev-2">
              <div className="text-fg-1">{entry.message}</div>
              <div className="font-mono text-[11px] text-fg-5">
                {entry.actor} · {entry.action} ·{" "}
                {formatDistanceToNow(new Date(entry.at), { addSuffix: true })}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReadinessCard(): React.ReactElement {
  const { data } = useDashboardReadiness();
  const blockers = data.blockers ?? [];
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="dashboard-readiness"
    >
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-fg-1">Release readiness</h3>
          <p className="text-[11.5px] text-fg-4">
            Deterministic checks (gating suite, defects, coverage)
          </p>
        </div>
        <ShieldCheck className="h-4 w-4 text-fg-4" aria-hidden="true" />
      </header>
      <div className="flex items-center gap-6">
        <Gauge value={data.score} label="Score" />
        <ul className="flex-1 space-y-2 text-[12.5px]">
          {blockers.length === 0 ? (
            <li className="flex items-center gap-2 text-fg-3">
              <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
              No blockers detected.
            </li>
          ) : (
            blockers.map((b, i) => (
              <li
                key={`${b.type}-${i.toString()}`}
                className="flex items-start gap-2 text-fg-3"
                data-testid="readiness-blocker"
              >
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red" aria-hidden="true" />
                <div className="flex flex-col">
                  <span className="text-fg-1">{b.message}</span>
                  <span className="font-mono text-[10.5px] text-fg-5">{b.type}</span>
                </div>
              </li>
            ))
          )}
        </ul>
      </div>
    </section>
  );
}

function DashboardHeader(): React.ReactElement {
  const { data: user } = useCurrentUser();
  const firstName = user?.name?.split(" ")[0] ?? user?.email?.split("@")[0] ?? "there";
  return (
    <header className="flex items-start justify-between gap-4" data-testid="dashboard-header">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2.5">
          <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">Dashboard</h2>
          <StatusBadge status="pass" label="All systems healthy" />
        </div>
        <p className="text-[12.5px] text-fg-3">
          Selamat siang, {firstName} — here&apos;s your test quality snapshot.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Window"
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2.5",
            "text-[12px] text-fg-3 hover:bg-bg-elev-2",
          )}
        >
          Last 7 days
          <ChevronDown className="h-3 w-3" aria-hidden="true" />
        </button>
        <Button type="button" size="sm" disabled aria-label="Run gating suite">
          Run gating suite
        </Button>
      </div>
    </header>
  );
}

function DashboardError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load dashboard"
      subtitle="The backend may be down. Retry, or check the API logs."
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function DashboardBody(): React.ReactElement {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <div className="flex flex-col gap-[18px]">
        <KpiSection />
        <div className="grid grid-cols-2 gap-[18px]">
          <PassRateCard />
          <CoverageCard />
        </div>
        <div className="grid grid-cols-2 gap-[18px]">
          <RecentRunsCard />
          <AgentActivityCard />
        </div>
        <ReadinessCard />
      </div>
    </Suspense>
  );
}

function Dashboard(): React.ReactElement {
  return (
    <section className="flex flex-col gap-[18px]" data-testid="dashboard-screen">
      <DashboardHeader />
      <ErrorBoundary fallback={({ reset }) => <DashboardError reset={reset} />}>
        <DashboardBody />
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/dashboard")({
  component: Dashboard,
  staticData: { title: "Dashboard" },
});

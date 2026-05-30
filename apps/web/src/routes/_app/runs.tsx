import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  Bot,
  Camera,
  Download,
  FileText,
  Globe,
  ListChecks,
  Maximize2,
  PlayCircle,
  Square,
} from "lucide-react";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import { Gated } from "@/components/gating/Gated";
import { RunsSkeleton } from "@/components/runs/skeleton";
import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";
import { CostChip } from "@/components/shared/CostChip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { SourceDot } from "@/components/shared/SourceDot";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useCancelRun,
  useRerunRun,
  useRun,
  useRunArtifacts,
  useRunLogs,
  useRunNetwork,
  useRunSteps,
  useRunsList,
  useRunsSummary,
} from "@/hooks/use-runs";
import { ApiError } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useCapabilities } from "@/stores/use-capabilities";

type RunListItem = components["schemas"]["RunListItem"];

interface SearchSchema {
  run?: string;
}

function statusToBadge(status: RunListItem["status"]):
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
    case "CANCELLED":
      return "warn";
    default:
      return "neutral";
  }
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

function SummaryBar(): React.ReactElement {
  const { data } = useRunsSummary();
  return (
    <section
      className="grid grid-cols-6 gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="runs-summary"
    >
      <Counter label="Active now" value={data.activeNow.toString()} accent />
      <Counter label="Today" value={data.today.toString()} />
      <Counter label="Passed" value={data.passed.toString()} />
      <Counter label="Failed" value={data.failed.toString()} />
      <Counter label="Avg duration" value={formatDuration(data.avgDurationMs)} />
      <Counter label="Queue" value={data.queue.toString()} />
    </section>
  );
}

function Counter({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}): React.ReactElement {
  return (
    <div className="flex flex-col gap-1" data-testid="runs-counter">
      <span className="text-[10.5px] uppercase tracking-wide text-fg-5">{label}</span>
      <span
        className={cn(
          "font-mono text-[18px] font-semibold tabular-nums",
          accent ? "text-accent" : "text-fg-1",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function RunsList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (publicId: string) => void;
}): React.ReactElement {
  const { data } = useRunsList(50);
  const runs = data.items;

  if (runs.length === 0) {
    return (
      <EmptyState
        icon={PlayCircle}
        title="No runs yet"
        subtitle="Manual + CI runs appear here as they execute."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-1" data-testid="runs-list">
      {runs.map((r) => {
        const passed = (r as RunListItem & { summary?: { passed_steps: number; total_steps: number } }).summary;
        const pct = passed?.total_steps ? (passed.passed_steps / passed.total_steps) * 100 : 0;
        return (
          <li key={r.id}>
            <button
              type="button"
              data-testid="runs-row"
              data-public-id={r.public_id}
              data-selected={r.public_id === selectedId ? "true" : "false"}
              onClick={() => {
                onSelect(r.public_id);
              }}
              className={cn(
                "flex w-full flex-col gap-1 rounded-md border border-transparent px-2 py-2 text-left hover:bg-bg-elev-2",
                r.public_id === selectedId && "border-border bg-bg-elev-2",
              )}
            >
              <div className="flex items-center gap-2 text-[12.5px]">
                <SourceDot status={statusToBadge(r.status)} />
                <span className="truncate text-fg-1">{r.name}</span>
              </div>
              <div className="flex items-center justify-between font-mono text-[10.5px] text-fg-5">
                <span>
                  {r.public_id} · {r.branch ?? "—"}
                  {r.commit_sha ? `@${r.commit_sha.slice(0, 7)}` : ""}
                </span>
                <span>{formatDuration(r.duration_ms)}</span>
              </div>
              <ProgressBar value={pct} variant={r.status === "FAIL" ? "fail" : "default"} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function DiagnosisCard({ runStatus }: { runStatus: RunListItem["status"] }): React.ReactElement | null {
  const tier = useCapabilities((s) => s.capabilities?.tier);
  if (runStatus !== "FAIL" && runStatus !== "ERROR") return null;

  if (tier !== "ZERO") {
    return (
      <Gated feature="ai_diagnose" fallback={null}>
        <AgentInsightCallout
          title="Agent diagnosis"
          confidence="High"
          body="Step 2 failed because the upstream payments service returned 500. Likely REGRESSION introduced in deploy 4b91a."
        />
      </Gated>
    );
  }

  return (
    <div
      className="flex items-start gap-3 rounded-md border border-border bg-bg-elev-2 p-3 text-fg-3"
      data-testid="manual-triage-card"
    >
      <Bot className="mt-0.5 h-4 w-4 text-fg-4" aria-hidden="true" />
      <div className="flex flex-col gap-1">
        <div className="text-[12.5px] font-semibold text-fg-1">Manual triage needed</div>
        <div className="text-[12px]">
          Pattern matched AssertionError on Step 2. ZERO tier — agent diagnosis unavailable.
        </div>
      </div>
    </div>
  );
}

function LogsPanel({ runId }: { runId: string }): React.ReactElement {
  const { data, isLoading, isError } = useRunLogs(runId);
  if (isLoading) return <div className="text-[12px] text-fg-4">Loading…</div>;
  if (isError || !data) return <div className="text-[12px] text-red">Failed to load logs</div>;
  const lines = data.lines ?? [];
  if (lines.length === 0) {
    return <div className="text-[12px] text-fg-4">No log lines yet.</div>;
  }
  return (
    <pre
      data-testid="run-logs"
      className="max-h-[480px] overflow-auto rounded-md bg-[#060606] p-[14px] font-mono text-[11.5px] leading-relaxed text-fg-1"
    >
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </pre>
  );
}

function StepsPanel({ runId, runStatus }: { runId: string; runStatus: RunListItem["status"] }): React.ReactElement {
  const { data, isLoading, isError } = useRunSteps(runId);
  if (isLoading) return <div className="text-[12px] text-fg-4">Loading…</div>;
  if (isError || !data) return <div className="text-[12px] text-red">Failed to load steps</div>;
  const items = data.items;
  return (
    <div className="flex flex-col gap-2" data-testid="run-steps">
      <DiagnosisCard runStatus={runStatus} />
      {items.length === 0 ? (
        <div className="text-[12px] text-fg-4">No steps recorded.</div>
      ) : (
        <ol className="flex flex-col gap-2">
          {items.map((s) => (
            <li
              key={s.id}
              className="rounded-md border border-border bg-bg-elev-1 p-3"
              data-testid="run-step"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-bg-elev-2 font-mono text-[10.5px] text-fg-4">
                    {s.step_order}
                  </span>
                  <span className="font-mono text-[11px] text-fg-4">{s.case_public_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge
                    status={
                      s.outcome === "PASS"
                        ? "pass"
                        : s.outcome === "FAIL" || s.outcome === "ERROR"
                          ? "fail"
                          : "neutral"
                    }
                  />
                  <span className="font-mono text-[10.5px] text-fg-5">
                    {formatDuration(s.duration_ms)}
                  </span>
                </div>
              </div>
              {s.error_message ? (
                <pre className="mt-2 overflow-x-auto rounded-md bg-[#060606] p-2 font-mono text-[11px] text-red">
                  {s.error_message}
                </pre>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ArtifactsPanel({ runId }: { runId: string }): React.ReactElement {
  const { data } = useRunArtifacts(runId);
  const items = data?.items ?? [];
  if (items.length === 0) {
    return <div className="text-[12px] text-fg-4">No artifacts captured.</div>;
  }
  return (
    <ul className="flex flex-col gap-1.5" data-testid="run-artifacts">
      {items.map((a) => (
        <li
          key={a.id}
          className="flex items-center justify-between rounded-md border border-border bg-bg-elev-1 p-2.5"
        >
          <div className="flex items-center gap-2 text-[12.5px]">
            <FileText className="h-3.5 w-3.5 text-fg-4" aria-hidden="true" />
            <span className="font-mono text-[11px] text-fg-3">{a.kind}</span>
            <span className="text-fg-1">{a.mime_type}</span>
            <span className="font-mono text-[10.5px] text-fg-5">{a.size_bytes}b</span>
          </div>
          <Button type="button" size="sm" variant="outline" disabled>
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Download
          </Button>
        </li>
      ))}
    </ul>
  );
}

function BrowserPanel(): React.ReactElement {
  return (
    <div className="rounded-md border border-border bg-bg-elev-1 p-3" data-testid="run-browser">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <span className="inline-block h-2 w-2 rounded-full bg-red" />
        <span className="inline-block h-2 w-2 rounded-full bg-amber" />
        <span className="inline-block h-2 w-2 rounded-full bg-accent" />
        <span className="ml-3 flex-1 rounded-md bg-bg-elev-2 px-2 py-0.5 font-mono text-[11px] text-fg-4">
          https://staging.example/checkout
        </span>
      </div>
      <div className="mt-3 flex h-[280px] items-center justify-center rounded-md bg-[#060606] text-[12px] text-fg-5">
        <Camera className="mr-2 h-4 w-4" aria-hidden="true" />
        Screenshot preview
      </div>
    </div>
  );
}

function NetworkPanel({ runId }: { runId: string }): React.ReactElement {
  const { data } = useRunNetwork(runId);
  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="text-[12px] text-fg-4" data-testid="run-network-empty">
        No network events recorded.
      </div>
    );
  }
  return (
    <table className="w-full text-[12px]" data-testid="run-network">
      <thead className="text-fg-5">
        <tr>
          <th className="px-2 py-1 text-left">Method</th>
          <th className="px-2 py-1 text-left">Path</th>
          <th className="px-2 py-1 text-left">Status</th>
          <th className="px-2 py-1 text-right">Duration</th>
        </tr>
      </thead>
      <tbody className="font-mono text-fg-3">
        {items.map((e, i) => (
          <tr key={i} className="border-t border-border">
            <td className="px-2 py-1">{e.method}</td>
            <td className="px-2 py-1">{e.path}</td>
            <td className="px-2 py-1">{e.status}</td>
            <td className="px-2 py-1 text-right">{e.durationMs}ms</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RunDetailPanel({
  runId,
  onNavigateToRun,
}: {
  runId: string | null;
  onNavigateToRun: (publicId: string) => void;
}): React.ReactElement {
  const [tab, setTab] = useState("logs");
  const { data: run, isLoading, isError } = useRun(runId ?? undefined);
  const cancelMutation = useCancelRun();
  const rerunMutation = useRerunRun();

  if (!runId) {
    return (
      <EmptyState
        icon={ListChecks}
        title="Select a run"
        subtitle="Pick a run from the list to view logs, steps, and artifacts."
      />
    );
  }
  if (isLoading || !run) return <RunsSkeleton />;
  if (isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Couldn't load run"
      />
    );
  }

  const isLive = run.status === "RUNNING" || run.status === "QUEUED";
  const cancelDisabled = !isLive || cancelMutation.isPending;
  // Re-run is only meaningful for terminal runs — guard against double-queueing.
  const rerunDisabled = isLive || rerunMutation.isPending;

  const handleCancel = (): void => {
    cancelMutation.mutate(run.id);
  };
  const handleRerun = (): void => {
    rerunMutation.mutate(run.id, {
      onSuccess: (data) => {
        onNavigateToRun(data.public_id);
      },
    });
  };

  // VIEWER role can't cancel — the backend returns 403; surface a non-blocking
  // capability banner instead of swallowing the error.
  const cancelForbidden =
    cancelMutation.error instanceof ApiError && cancelMutation.error.status === 403;

  return (
    <div className="flex flex-col gap-4" data-testid="run-detail">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <StatusBadge status={statusToBadge(run.status)} />
          <span className="font-mono text-[12px] text-fg-3">{run.public_id}</span>
          <span className="font-mono text-[11px] text-fg-5">via {run.trigger}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={cancelDisabled}
            onClick={handleCancel}
            data-testid="run-cancel-button"
          >
            <Square className="h-3.5 w-3.5" aria-hidden="true" />
            {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rerunDisabled}
            onClick={handleRerun}
            data-testid="run-rerun-button"
          >
            {rerunMutation.isPending ? "Queuing…" : "Re-run"}
          </Button>
          <Button type="button" size="sm" variant="ghost" disabled aria-label="Fullscreen">
            <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {cancelForbidden ? (
        <div
          role="alert"
          data-testid="run-cancel-forbidden-banner"
          className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12px] text-red"
        >
          Cancelling runs requires QA access. Ask an admin to grant it.
        </div>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <h3 className="text-[18px] font-semibold leading-tight tracking-[-.01em] text-fg-1">
          {run.name}
        </h3>
        <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-fg-4">
          <span>
            {run.branch ?? "—"}
            {run.commit_sha ? `@${run.commit_sha.slice(0, 7)}` : ""}
          </span>
          <span>env={run.env}</span>
          <span>duration={formatDuration(run.duration_ms)}</span>
          <span>tier={run.tier_at_runtime}</span>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab} data-testid="run-tabs">
        <TabsList variant="line">
          <TabsTrigger value="logs">
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            Logs
          </TabsTrigger>
          <TabsTrigger value="steps">Steps</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="browser">Browser</TabsTrigger>
          <TabsTrigger value="network">
            <Globe className="h-3.5 w-3.5" aria-hidden="true" />
            Network
          </TabsTrigger>
        </TabsList>
        <TabsContent value="logs">
          <LogsPanel runId={run.id} />
        </TabsContent>
        <TabsContent value="steps">
          <StepsPanel runId={run.id} runStatus={run.status} />
        </TabsContent>
        <TabsContent value="artifacts">
          <ArtifactsPanel runId={run.id} />
        </TabsContent>
        <TabsContent value="browser">
          <BrowserPanel />
        </TabsContent>
        <TabsContent value="network">
          <NetworkPanel runId={run.id} />
        </TabsContent>
      </Tabs>

      <footer className="flex justify-end" data-testid="run-cost-footer">
        <Gated
          feature="ai_conversation"
          fallback={<span className="font-mono text-[11px] text-fg-5">$0 · deterministic</span>}
        >
          <CostChip tokens={0} cost={0} provider="anthropic" toolCalls={0} />
        </Gated>
      </footer>
    </div>
  );
}

function RunsBody(): React.ReactElement {
  const search = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const selected = search.run ?? null;

  return (
    <>
      <SummaryBar />
      <div className="grid grid-cols-[260px_1fr] gap-4">
        <aside
          className="rounded-md border border-border bg-bg-elev-1 p-2"
          data-testid="runs-left-pane"
        >
          <RunsList
            selectedId={selected}
            onSelect={(publicId) => {
              void navigate({ search: { run: publicId } });
            }}
          />
        </aside>
        <section
          className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
          data-testid="runs-right-pane"
        >
          <RunDetailPanel
            runId={selected}
            onNavigateToRun={(publicId) => {
              void navigate({ search: { run: publicId } });
            }}
          />
        </section>
      </div>
    </>
  );
}

function RunsError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load runs"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function RunsScreen(): React.ReactElement {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-4" data-testid="runs-screen">
      <header>
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">{t("runs.title")}</h2>
      </header>
      <ErrorBoundary fallback={({ reset }) => <RunsError reset={reset} />}>
        <Suspense fallback={<RunsSkeleton />}>
          <RunsBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/runs")({
  component: RunsScreen,
  staticData: { title: "Test Runs" },
  validateSearch: (search: Record<string, unknown>): SearchSchema => {
    const raw = search["run"];
    return typeof raw === "string" ? { run: raw } : {};
  },
});

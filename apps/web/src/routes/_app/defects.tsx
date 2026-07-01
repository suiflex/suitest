import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, Bug, ExternalLink, Play } from "lucide-react";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import { DefectsSkeleton } from "@/components/defects/skeleton";
import { Gated } from "@/components/gating/Gated";
import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { useDefects, useFetchDefectDetail } from "@/hooks/use-defects";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useCapabilities } from "@/stores/use-capabilities";

type Defect = components["schemas"]["DefectListItem"];

function severityClass(sev: Defect["severity"]): string {
  switch (sev) {
    case "CRITICAL":
      return "bg-red/15 text-red border-red/20";
    case "HIGH":
      return "bg-red/10 text-red border-red/20";
    case "MEDIUM":
      return "bg-amber/10 text-amber border-amber/20";
    default:
      return "bg-bg-elev-2 text-fg-3 border-border";
  }
}

function statusBadgeForDefect(status: Defect["status"]): "fail" | "warn" | "neutral" | "pass" {
  switch (status) {
    case "OPEN":
      return "fail";
    case "IN_PROGRESS":
      return "warn";
    case "RESOLVED":
    case "CLOSED":
      return "pass";
    default:
      return "neutral";
  }
}

function DefectCard({ defect }: { defect: Defect }): React.ReactElement {
  const tier = useCapabilities((s) => s.capabilities?.tier);
  const showAgent = tier !== "ZERO";
  const navigate = useNavigate();
  const fetchDetail = useFetchDefectDetail();

  // M1d-32: replace the M1c-era disabled "Re-run" stub with a flow that
  // fetches the defect detail to read ``run_public_id`` then navigates to
  // the run detail screen, where the M1c-shipped ``POST /runs/:id/rerun``
  // is already wired (see runs.tsx Cancel/Rerun buttons).
  const handleOpenRun = (): void => {
    fetchDetail.mutate(defect.public_id, {
      onSuccess: (detail) => {
        if (detail.run_public_id) {
          void navigate({
            to: "/runs/$runId",
            params: { runId: detail.run_public_id },
          });
        }
      },
    });
  };
  const openRunPending = fetchDetail.isPending;
  const noLinkedRun = fetchDetail.isSuccess && fetchDetail.data?.run_public_id == null;

  return (
    <article
      data-testid="defect-card"
      data-defect-id={defect.public_id}
      className="flex flex-col gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wide",
              severityClass(defect.severity),
            )}
            data-testid="defect-severity"
          >
            {defect.severity}
          </span>
          <StatusBadge status={statusBadgeForDefect(defect.status)} label={defect.status} />
          <span
            className="rounded-md border border-blue/20 bg-blue/10 px-2 py-0.5 font-mono text-[11px] text-blue"
            data-testid="defect-public-id"
          >
            {defect.public_id}
          </span>
          <span className="font-mono text-[10.5px] text-fg-5">
            {formatDistanceToNow(new Date(defect.created_at), { addSuffix: true })}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Button type="button" size="sm" variant="outline" disabled>
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            View in Jira
          </Button>
          {noLinkedRun ? (
            <DisabledTooltip reason="This defect has no linked run yet.">
              <Button type="button" size="sm" disabled>
                <Play className="h-3.5 w-3.5" aria-hidden="true" />
                Open run
              </Button>
            </DisabledTooltip>
          ) : (
            <Button
              type="button"
              size="sm"
              data-testid="defect-open-run-btn"
              disabled={openRunPending}
              onClick={handleOpenRun}
            >
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
              {openRunPending ? "Loading…" : "Open run"}
            </Button>
          )}
        </div>
      </header>

      <h3 className="text-[14px] font-semibold text-fg-1">{defect.title}</h3>

      <div className="grid grid-cols-2 gap-3">
        <pre
          className="overflow-auto rounded-md bg-bg-code p-3 font-mono text-[11.5px] leading-relaxed text-fg-3"
          data-testid="defect-stack"
        >
          <code>
            <span className="text-red">AssertionError: expected 200 got 500</span>
            {"\n  at apps/api/src/routers/checkout.py:142"}
            {"\n  at validate_card(payload=...)"}
            {"\n  at checkout_request(POST /checkout)"}
          </code>
        </pre>
        <div data-testid="defect-diagnosis-area">
          {showAgent ? (
            <Gated
              feature="ai_diagnose"
              fallback={<ManualTriageCard kind={defect.agent_diagnosis_kind} />}
            >
              <AgentInsightCallout
                title="Agent diagnosis"
                confidence={defect.agent_diagnosis_kind === "FLAKE" ? "Medium" : "High"}
                body={`Detected as ${defect.agent_diagnosis_kind}. Likely cause attached in the run trace.`}
              />
            </Gated>
          ) : (
            <ManualTriageCard kind={defect.agent_diagnosis_kind} />
          )}
        </div>
      </div>

      <footer className="flex flex-wrap items-center gap-3 border-t border-border pt-3 font-mono text-[11px] text-fg-4">
        <span>Component: {defect.component ?? "—"}</span>
        <span>Assignee: {defect.assignee_id ?? "—"}</span>
        <span>Updated {formatDistanceToNow(new Date(defect.updated_at), { addSuffix: true })}</span>
      </footer>
    </article>
  );
}

function ManualTriageCard({
  kind,
}: {
  kind: components["schemas"]["DiagnosisKind"];
}): React.ReactElement {
  return (
    <div
      data-testid="defect-manual-triage"
      className="flex h-full flex-col items-start justify-center gap-1 rounded-md border border-border bg-bg-elev-2 p-3 text-fg-3"
    >
      <div className="text-[12.5px] font-semibold text-fg-1">Manual triage needed</div>
      <p className="text-[12px]">
        Rule-based hint: pattern matched <span className="font-mono text-fg-4">{kind}</span>. Open
        the run for stack trace + step context.
      </p>
    </div>
  );
}

function DefectsList(): React.ReactElement {
  const { data } = useDefects({ status: "OPEN" });
  const items = data.items;

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Bug}
        title="No open defects"
        subtitle="Defects show up here when runs fail or you file one manually."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3.5" data-testid="defects-list">
      {items.map((d) => (
        <DefectCard key={d.id} defect={d} />
      ))}
    </div>
  );
}

function DefectsHeader(): React.ReactElement {
  const { t } = useTranslation();
  return (
    <header className="flex items-center justify-between" data-testid="defects-header">
      <div className="flex items-center gap-2.5">
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">
          {t("defects.title")}
        </h2>
        <Suspense fallback={null}>
          <OpenCountBadge />
        </Suspense>
      </div>
      <Gated feature="ai_diagnose" fallback={null}>
        <Suspense fallback={null}>
          <AutoFiledBadge />
        </Suspense>
      </Gated>
    </header>
  );
}

function OpenCountBadge(): React.ReactElement | null {
  const { data } = useDefects({ status: "OPEN" });
  if (data.items.length === 0) return null;
  return (
    <span
      data-testid="defects-open-count"
      className="inline-flex items-center rounded-full bg-red/15 px-2 py-0.5 text-[11px] font-medium text-red"
    >
      {data.items.length} open
    </span>
  );
}

function AutoFiledBadge(): React.ReactElement | null {
  // Stubbed value — real count comes from /audit-logs filter in M2.
  return (
    <span
      data-testid="defects-auto-filed"
      className="inline-flex items-center rounded-full border border-violet/30 bg-violet/10 px-2 py-0.5 text-[11px] font-medium text-violet"
    >
      Auto-filed by agent
    </span>
  );
}

function DefectsError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load defects"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Defects(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="defects-screen">
      <ErrorBoundary fallback={({ reset }) => <DefectsError reset={reset} />}>
        <DefectsHeader />
        <Suspense fallback={<DefectsSkeleton />}>
          <DefectsList />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/defects")({
  component: Defects,
  staticData: { title: "Defects" },
});

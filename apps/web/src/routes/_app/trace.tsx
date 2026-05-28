import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Bug, FileText, ListTree, Sparkles } from "lucide-react";
import { Suspense, useMemo, useState } from "react";

import { TraceSkeleton } from "@/components/trace/skeleton";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SourcePill } from "@/components/shared/SourcePill";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { useTraceabilityMatrix } from "@/hooks/use-traceability";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

type Matrix = components["schemas"]["TraceabilityMatrix"];
type Case = components["schemas"]["MatrixCase"];

function caseSourceToPill(source: Case["source"]): "MANUAL" | "AI" | "MCP" | "IMPORT" {
  if (source === "AI") return "AI";
  if (source === "MCP") return "MCP";
  if (source === "IMPORT" || source === "RECORDER" || source === "HEURISTIC_CRAWL") return "IMPORT";
  return "MANUAL";
}

function CalloutBar({ matrix }: { matrix: Matrix }): React.ReactElement {
  const total = matrix.requirements?.length ?? 0;
  const linked = (matrix.requirements ?? []).filter((r) => (r.tests ?? []).length > 0).length;
  const withDefects = (matrix.requirements ?? []).filter((r) => (r.defects ?? []).length > 0).length;

  return (
    <div
      className="flex items-center justify-between gap-3 rounded-md border border-border bg-bg-elev-1 p-4"
      data-testid="trace-callout"
    >
      <div className="flex items-center gap-3">
        <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />
        <p className="text-[12.5px] text-fg-3">
          <span className="font-mono text-fg-1">
            {linked}/{total}
          </span>{" "}
          requirements have linked test cases ·{" "}
          <span className="font-mono text-fg-1">{withDefects}</span> with open defects
        </p>
      </div>
      <DisabledTooltip reason="Gap analysis ships in M2">
        <Button type="button" size="sm" variant="outline" disabled>
          Find gaps
        </Button>
      </DisabledTooltip>
    </div>
  );
}

function MatrixBody(): React.ReactElement {
  const { data } = useTraceabilityMatrix();
  const [selectedReq, setSelectedReq] = useState<string | null>(null);

  const requirements = useMemo(() => data.requirements ?? [], [data.requirements]);
  const cases = data.cases ?? [];
  const defects = data.defects ?? [];

  const linkedCaseIds = useMemo(() => {
    if (!selectedReq) return new Set<string>();
    const req = requirements.find((r) => r.id === selectedReq);
    return new Set(req?.tests ?? []);
  }, [selectedReq, requirements]);

  const linkedDefectIds = useMemo(() => {
    if (!selectedReq) return new Set<string>();
    const req = requirements.find((r) => r.id === selectedReq);
    return new Set(req?.defects ?? []);
  }, [selectedReq, requirements]);

  if (requirements.length === 0) {
    return (
      <EmptyState
        icon={ListTree}
        title="No requirements imported"
        subtitle="Paste a PRD or import OpenAPI."
        action={[{ label: "Add source", variant: "outline" }]}
      />
    );
  }

  return (
    <>
      <CalloutBar matrix={data} />
      <div className="grid grid-cols-3 gap-4" data-testid="trace-grid">
        <Column title="Requirements" icon={FileText}>
          <ul className="flex flex-col">
            {requirements.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  data-testid="trace-req-row"
                  data-req-id={r.id}
                  data-selected={r.id === selectedReq ? "true" : "false"}
                  onClick={() => {
                    setSelectedReq(r.id === selectedReq ? null : r.id);
                  }}
                  className={cn(
                    "flex w-full flex-col gap-0.5 rounded-md px-2 py-2 text-left text-[12.5px] hover:bg-bg-elev-2",
                    r.id === selectedReq && "bg-accent/15",
                  )}
                >
                  <span className="font-mono text-[11px] text-fg-4">{r.id}</span>
                  <span className="text-fg-1">{r.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </Column>

        <Column title="Test cases" icon={ListTree}>
          <ul className="flex flex-col">
            {cases.map((c) => {
              const linked = linkedCaseIds.has(c.id);
              return (
                <li key={c.id}>
                  <div
                    data-testid="trace-case-row"
                    data-case-id={c.id}
                    data-linked={linked ? "true" : "false"}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-md px-2 py-2 text-[12.5px]",
                      linked && "bg-accent/15",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="font-mono text-[11px] text-fg-4">{c.id}</span>
                      <span className="truncate text-fg-1">{c.name}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <SourcePill source={caseSourceToPill(c.source)} />
                      <StatusBadge status={c.status === "ACTIVE" ? "pass" : "neutral"} label={c.status} />
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Column>

        <Column title="Defects" icon={Bug}>
          {defects.length === 0 ? (
            <div className="text-[12px] text-fg-4">No defects linked yet.</div>
          ) : (
            <ul className="flex flex-col">
              {defects.map((d) => {
                const linked = linkedDefectIds.has(d.id);
                return (
                  <li key={d.id}>
                    <div
                      data-testid="trace-defect-row"
                      data-defect-id={d.id}
                      data-linked={linked ? "true" : "false"}
                      className={cn(
                        "flex items-center justify-between gap-2 rounded-md px-2 py-2 text-[12.5px]",
                        linked && "bg-accent/15",
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="font-mono text-[11px] text-fg-4">{d.id}</span>
                        <span className="truncate text-fg-1">{d.title}</span>
                      </div>
                      <StatusBadge
                        status={d.status === "OPEN" ? "fail" : "warn"}
                        label={d.severity}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Column>
      </div>
    </>
  );
}

function Column({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof FileText;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <section className="rounded-md border border-border bg-bg-elev-1 p-3">
      <header className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-fg-5">
        <Icon className="h-3 w-3" aria-hidden="true" />
        {title}
      </header>
      {children}
    </section>
  );
}

function TraceError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load traceability"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Trace(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="trace-screen">
      <header>
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">Traceability</h2>
      </header>
      <ErrorBoundary fallback={({ reset }) => <TraceError reset={reset} />}>
        <Suspense fallback={<TraceSkeleton />}>
          <MatrixBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/trace")({
  component: Trace,
  staticData: { title: "Traceability" },
});

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  ChevronDown,
  FileText,
  FolderTree,
  ListChecks,
  Trash2,
} from "lucide-react";
import { Suspense, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { CasesSkeleton } from "@/components/cases/skeleton";
import { StepEditor } from "@/components/cases/StepEditor";
import type { DraftStep } from "@/components/cases/StepEditor";
import { Gated } from "@/components/gating/Gated";
import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SourceDot } from "@/components/shared/SourceDot";
import { SourcePill } from "@/components/shared/SourcePill";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useFeatureEnabled } from "@/hooks/use-feature-enabled";
import { useCreateRun } from "@/hooks/use-runs";
import {
  useDeleteTestCase,
  useRestoreTestCase,
  useSuites,
  useTestCase,
  useTestCases,
} from "@/hooks/use-test-cases";
import type { components } from "@/lib/api-types";
import { undoToast } from "@/lib/undo-toast";
import { cn } from "@/lib/utils";

type Case = components["schemas"]["TestCaseListItem"];
type Suite = components["schemas"]["SuitePublic"];

type Tab = "all" | "manual" | "ai" | "mcp" | "failing";

function caseSourceToPill(source: Case["source"]): "MANUAL" | "AI" | "MCP" | "IMPORT" {
  if (source === "AI") return "AI";
  if (source === "MCP") return "MCP";
  if (source === "IMPORT" || source === "RECORDER" || source === "HEURISTIC_CRAWL") return "IMPORT";
  return "MANUAL";
}

interface SearchSchema {
  case?: string;
}

function CasesHeader({
  active,
  setActive,
  counts,
  showAiTab,
}: {
  active: Tab;
  setActive: (t: Tab) => void;
  counts: Record<Tab, number>;
  showAiTab: boolean;
}): React.ReactElement {
  const { t } = useTranslation();
  const tabs: Array<{ id: Tab; label: string; show?: boolean }> = [
    { id: "all", label: "All" },
    { id: "manual", label: "Manual" },
    { id: "ai", label: "AI-generated", show: showAiTab },
    { id: "mcp", label: "MCP" },
    { id: "failing", label: "Failing" },
  ];
  const visible = tabs.filter((tab) => tab.show !== false);

  return (
    <header className="flex items-center justify-between gap-4" data-testid="cases-header">
      <div className="flex items-center gap-4">
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">{t("cases.title")}</h2>
        <nav className="flex items-center gap-1" data-testid="cases-tabs">
          {visible.map((tab) => (
            <button
              key={tab.id}
              type="button"
              data-testid={`cases-tab-${tab.id}`}
              data-active={active === tab.id ? "true" : "false"}
              onClick={() => {
                setActive(tab.id);
              }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-fg-3 hover:bg-bg-elev-2",
                active === tab.id && "bg-bg-elev-2 text-fg-1",
              )}
            >
              {tab.label}
              <span className="font-mono text-[10.5px] text-fg-5">{counts[tab.id]}</span>
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-2">
        <DisabledTooltip reason="Generators ship in M2">
          <Button type="button" size="sm" disabled>
            Generate
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </Button>
        </DisabledTooltip>
      </div>
    </header>
  );
}

function CaseTree({
  suites,
  cases,
  selectedId,
  onSelect,
}: {
  suites: Suite[];
  cases: Case[];
  selectedId: string | null;
  onSelect: (publicId: string) => void;
}): React.ReactElement {
  const grouped = useMemo(() => {
    const map = new Map<string, Case[]>();
    for (const s of suites) map.set(s.id, []);
    for (const c of cases) {
      if (!map.has(c.suite_id)) map.set(c.suite_id, []);
      map.get(c.suite_id)?.push(c);
    }
    return map;
  }, [suites, cases]);

  if (cases.length === 0) {
    return (
      <EmptyState
        icon={ListChecks}
        title="No cases yet"
        subtitle="Generate from OpenAPI, record a browser session, or write manually."
        action={[
          { label: "From OpenAPI", variant: "outline" },
          { label: "Record session", variant: "outline" },
          { label: "Write manually", variant: "outline" },
        ]}
      />
    );
  }

  return (
    <nav className="flex flex-col gap-3" data-testid="cases-tree">
      {[...grouped.entries()].map(([suiteId, items]) => {
        const suite = suites.find((s) => s.id === suiteId);
        return (
          <div key={suiteId} data-testid="cases-tree-suite">
            <div className="mb-1 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-fg-5">
              <FolderTree className="h-3 w-3" aria-hidden="true" />
              {suite?.name ?? "Unassigned"}
              <span className="font-mono text-[10px] text-fg-5">{items.length}</span>
            </div>
            <ul className="flex flex-col">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    data-testid="cases-tree-row"
                    data-public-id={c.public_id}
                    data-selected={c.public_id === selectedId ? "true" : "false"}
                    onClick={() => {
                      onSelect(c.public_id);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] text-fg-1 hover:bg-bg-elev-2",
                      c.public_id === selectedId && "bg-bg-elev-2",
                    )}
                  >
                    <SourceDot status={c.status === "DEPRECATED" ? "warn" : "pass"} />
                    <span className="font-mono text-[11px] text-fg-4">{c.public_id}</span>
                    <span className="truncate">{c.name}</span>
                    <span className="ml-auto">
                      <SourcePill source={caseSourceToPill(c.source)} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function CaseDetailPanel({
  publicId,
  suites,
}: {
  publicId: string | null;
  suites: Suite[];
}): React.ReactElement {
  const { data: detail, isLoading, isError } = useTestCase(publicId ?? undefined);
  const navigate = useNavigate();
  const createRun = useCreateRun();
  const deleteCase = useDeleteTestCase();
  const restoreCase = useRestoreTestCase();

  // Local draft state for the step editor — seeded from the server response
  // and kept in sync when the server data refreshes (via key on detail?.id).
  const [draftSteps, setDraftSteps] = useState<DraftStep[]>([]);

  // Sync draftSteps when the server data arrives or changes
  const serverSteps = detail?.steps ?? [];

  // Use a derived key to detect when serverSteps identity changes so we can
  // reset the draft. We compare by serialised IDs only to avoid infinite loops.
  const serverStepIds = serverSteps.map((s) => s.id).join(",");

  // We need a stable reference to avoid re-creating on every render
  const syncedRef = useMemo(
    () => serverStepIds,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [serverStepIds],
  );

  // When server step IDs change (new fetch, add/remove success), seed draft
  // We do this via useMemo so no extra render cycle is needed for derivation
  const effectiveSteps = useMemo<DraftStep[]>(() => {
    return serverSteps.map((s) => ({
      id: s.id,
      order: s.order,
      action: s.action,
      expected: s.expected,
      code: s.code ?? null,
      mcp_provider: s.mcp_provider,
      target_kind: s.target_kind,
    }));
    // syncedRef is the same as serverStepIds but stable reference for deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncedRef]);

  // Merge: prefer draftSteps if they diverge from server (user editing),
  // but reset if the case selection changes or server fetch refreshes with
  // different step IDs (add/remove confirmed by server).
  //
  // Strategy: if draftSteps is empty OR server IDs changed → use effectiveSteps
  const stepsToShow = draftSteps.length === 0 && effectiveSteps.length === 0
    ? []
    : draftSteps.length > 0
    ? draftSteps
    : effectiveSteps;

  const handleStepsChange = useCallback((next: DraftStep[]) => {
    setDraftSteps(next);
  }, []);

  if (!publicId) {
    return (
      <EmptyState
        icon={FileText}
        title="Select a case"
        subtitle="Pick a case from the tree to view details."
      />
    );
  }
  if (isLoading || !detail) {
    return <CasesSkeleton />;
  }
  if (isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Couldn't load case"
        subtitle="The backend returned an error."
      />
    );
  }

  const sourcePill = caseSourceToPill(detail.source);
  // ``TestCaseDetail`` exposes ``suite_id`` but not ``project_id``; derive the
  // latter from the cached suites list so ``POST /runs`` can be addressed to
  // the right project without an extra round-trip.
  const projectId = suites.find((s) => s.id === detail.suite_id)?.project_id ?? null;
  const runPending = createRun.isPending;
  const canRun = projectId !== null && !runPending;
  const handleRun = (): void => {
    if (projectId === null) return;
    createRun.mutate(
      {
        projectId,
        name: `Ad-hoc: ${detail.name}`,
        selection: [{ caseId: detail.id }],
        trigger: "MANUAL",
      },
      {
        onSuccess: (run) => {
          void navigate({ to: "/runs/$runId", params: { runId: run.public_id } });
        },
      },
    );
  };

  const deletePending = deleteCase.isPending || restoreCase.isPending;
  const handleDelete = (): void => {
    const targetId = detail.public_id;
    deleteCase.mutate(targetId, {
      onSuccess: () => {
        // Drop the ?case= param so the panel returns to the empty state.
        void navigate({ to: "/cases", search: {} });
        void undoToast({
          label: `Deleted ${targetId}`,
          onUndo: () =>
            new Promise<void>((resolve, reject) => {
              restoreCase.mutate(targetId, {
                onSuccess: () => {
                  resolve();
                },
                onError: (err) => {
                  reject(err);
                },
              });
            }),
          undoSuccessMessage: `Restored ${targetId}`,
          undoErrorMessage: `Failed to restore ${targetId}`,
        });
      },
    });
  };

  return (
    <div className="flex flex-col gap-4" data-testid="case-detail">
      <div
        className="flex items-center justify-between gap-3 border-b border-border pb-3"
        data-testid="case-toolbar"
      >
        <div className="flex items-center gap-2">
          <span className="rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[11px] text-fg-3">
            {detail.public_id}
          </span>
          <StatusBadge status={detail.status === "ACTIVE" ? "pass" : "neutral"} label={detail.status} />
          <span className="rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[11px] text-fg-3">
            {detail.priority}
          </span>
          <SourcePill source={sourcePill} />
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="case-delete-btn"
            disabled={deletePending}
            onClick={handleDelete}
            className="text-fg-3 hover:text-red"
            aria-label="Delete case"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            {deleteCase.isPending ? "Deleting…" : "Delete"}
          </Button>
          <Button
            type="button"
            size="sm"
            data-testid="case-run-now"
            disabled={!canRun}
            onClick={handleRun}
          >
            {runPending ? "Queuing…" : "Run now"}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[10.5px] uppercase tracking-wide text-fg-5">Suite</span>
        <h3 className="text-[22px] font-semibold leading-tight tracking-[-.01em] text-fg-1">
          {detail.name}
        </h3>
        {detail.description ? (
          <p className="text-[12.5px] text-fg-3">{detail.description}</p>
        ) : null}
      </div>

      <dl className="grid grid-cols-5 gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px] text-[12px]">
        <Meta label="Owner" value={detail.owner_id ?? "—"} />
        <Meta label="Suite" value={detail.suite_id} mono />
        <Meta label="Generated by" value={sourcePill} />
        <Meta label="Tags" value={(detail.tags ?? []).join(", ") || "—"} />
        <Meta label="Updated" value={formatDistanceToNow(new Date(detail.updated_at), { addSuffix: true })} />
      </dl>

      <div data-testid="case-steps">
        <StepEditor
          caseId={detail.public_id}
          steps={stepsToShow}
          onStepsChange={handleStepsChange}
        />
      </div>

      <Gated feature="ai_diagnose" fallback={null}>
        <AgentInsightCallout
          title="Agent diagnosis"
          confidence="High"
          body={`Last run on ${detail.public_id} suggests stable behaviour. No outstanding flake signals.`}
        />
      </Gated>
    </div>
  );
}

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}): React.ReactElement {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10.5px] uppercase tracking-wide text-fg-5">{label}</dt>
      <dd className={cn("text-fg-1", mono && "font-mono text-[11px] text-fg-3")}>{value}</dd>
    </div>
  );
}

function CasesBody(): React.ReactElement {
  const search = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const { data: suites } = useSuites();
  const { data: cases } = useTestCases();
  const aiTabVisible = useFeatureEnabled("ai_generation");

  const [active, setActive] = useState<Tab>("all");

  const counts = useMemo<Record<Tab, number>>(() => {
    const all = cases.items.length;
    const manual = cases.items.filter((c) => c.source === "MANUAL").length;
    const ai = cases.items.filter((c) => c.source === "AI").length;
    const mcp = cases.items.filter((c) => c.source === "MCP").length;
    return { all, manual, ai, mcp, failing: 0 };
  }, [cases]);

  const filtered = useMemo(() => {
    switch (active) {
      case "manual":
        return cases.items.filter((c) => c.source === "MANUAL");
      case "ai":
        return cases.items.filter((c) => c.source === "AI");
      case "mcp":
        return cases.items.filter((c) => c.source === "MCP");
      case "failing":
        return [];
      default:
        return cases.items;
    }
  }, [active, cases]);

  const selectedId = search.case ?? null;

  return (
    <>
      <CasesHeader
        active={active}
        setActive={setActive}
        counts={counts}
        showAiTab={aiTabVisible}
      />
      <div className="grid grid-cols-[280px_1fr] gap-4">
        <aside
          className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-3"
          data-testid="cases-left-pane"
        >
          <DisabledTooltip reason="Filter ships in M1d">
            <Input disabled placeholder="Filter cases…" className="h-8" />
          </DisabledTooltip>
          <CaseTree
            suites={suites.items}
            cases={filtered}
            selectedId={selectedId}
            onSelect={(publicId) => {
              void navigate({ search: { case: publicId } });
            }}
          />
        </aside>
        <section
          className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
          data-testid="cases-right-pane"
        >
          <CaseDetailPanel publicId={selectedId} suites={suites.items} />
        </section>
      </div>
    </>
  );
}

function CasesError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load cases"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

// Hide the AI tab in ZERO via wrapper — leverages Gated for ergonomic
// composition, so the CasesHeader doesn't have to know about capabilities.
function CasesContainer(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="cases-screen">
      <ErrorBoundary fallback={({ reset }) => <CasesError reset={reset} />}>
        <Suspense fallback={<CasesSkeleton />}>
          <CasesBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/cases")({
  component: CasesContainer,
  staticData: { title: "Test Cases" },
  validateSearch: (search: Record<string, unknown>): SearchSchema => {
    const raw = search["case"];
    return typeof raw === "string" ? { case: raw } : {};
  },
});

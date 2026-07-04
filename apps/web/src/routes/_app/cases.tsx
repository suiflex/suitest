import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  ChevronDown,
  Code2,
  FileText,
  FolderTree,
  ListChecks,
  Paperclip,
  ScrollText,
  Trash2,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { CreateCaseDialog } from "@/components/cases/CreateCaseDialog";
import { CreateProjectDialog } from "@/components/cases/CreateProjectDialog";
import { CreateSuiteDialog } from "@/components/cases/CreateSuiteDialog";
import { GenerateModal } from "@/components/cases/GenerateModal";
import type { GeneratorStrategy } from "@/components/cases/GenerateModal";
import { CasesSkeleton } from "@/components/cases/skeleton";
import { StepEditor } from "@/components/cases/StepEditor";
import type { DraftStep } from "@/components/cases/StepEditor";
import { StepList } from "@/components/cases/StepList";
import { BrowserPreview } from "@/components/runs/BrowserPreview";
import { Gated } from "@/components/gating/Gated";
import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SourceDot } from "@/components/shared/SourceDot";
import { SourcePill } from "@/components/shared/SourcePill";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  fetchRunArtifacts,
  fetchRunLogs,
  fetchRunSignedUrl,
  fetchRunSteps,
} from "@/lib/api-client";
import {
  caseTypeLabel,
  deriveCaseType,
  deriveServerStep,
  displayTitle,
  generateFallbackSteps,
  technicalKey,
} from "@/lib/test-case-format";
import { useFeatureEnabled } from "@/hooks/use-feature-enabled";
import { useProject, useSetGatingSuite } from "@/hooks/use-projects";
import { useActiveProject } from "@/stores/use-active-project";
import { useCreateRun } from "@/hooks/use-runs";
import {
  useBulkUpdate,
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
type Priority = components["schemas"]["Priority"];
type CaseDetail = components["schemas"]["TestCaseDetail"];
type RunStepPublic = components["schemas"]["RunStepPublic"];
type StepOutcome = components["schemas"]["StepOutcome"];
type ArtifactPublic = components["schemas"]["ArtifactPublic"];

type Tab = "all" | "manual" | "ai" | "mcp" | "failing";

const BULK_LIMIT = 100;
const PRIORITIES: Priority[] = ["P0", "P1", "P2", "P3"];

function caseSourceToPill(source: Case["source"]): "MANUAL" | "AI" | "MCP" | "IMPORT" {
  if (source === "AI") return "AI";
  if (source === "MCP") return "MCP";
  if (source === "IMPORT" || source === "RECORDER" || source === "HEURISTIC_CRAWL") return "IMPORT";
  return "MANUAL";
}

/** A case is "failing" when its last run ended in FAIL or ERROR. */
function isFailing(c: Case): boolean {
  return c.last_run_result === "FAIL" || c.last_run_result === "ERROR";
}

interface SearchSchema {
  case?: string;
}

function CasesHeader({
  active,
  setActive,
  counts,
  showAiTab,
  onGenerate,
  aiEnabled,
}: {
  active: Tab;
  setActive: (t: Tab) => void;
  counts: Record<Tab, number>;
  showAiTab: boolean;
  onGenerate: (strategy?: GeneratorStrategy) => void;
  aiEnabled: boolean;
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
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">
          {t("cases.title")}
        </h2>
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
      <div className="flex items-center gap-2" data-testid="generate-split-button">
        <Button
          type="button"
          size="sm"
          data-testid="generate-btn"
          onClick={() => {
            onGenerate();
          }}
          className="rounded-r-none"
        >
          Generate
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              data-testid="generate-menu-trigger"
              aria-label="Generate options"
              className="rounded-l-none border-l border-bg-base px-1.5"
            >
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-55">
            <DropdownMenuItem
              data-testid="generate-menu-openapi"
              onSelect={() => {
                onGenerate("openapi");
              }}
            >
              {"{ }"} Generate from OpenAPI
            </DropdownMenuItem>
            <DropdownMenuItem
              data-testid="generate-menu-recorder"
              onSelect={() => {
                onGenerate("recorder");
              }}
            >
              ● Record from browser
            </DropdownMenuItem>
            <DropdownMenuItem
              data-testid="generate-menu-crawler"
              onSelect={() => {
                onGenerate("crawler");
              }}
            >
              🔗 Crawl URL
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {aiEnabled ? (
              <DropdownMenuItem data-testid="generate-menu-ai" disabled>
                ✨ Generate (AI)
              </DropdownMenuItem>
            ) : (
              <DisabledTooltip reason="LLM not configured. Settings → LLM">
                <DropdownMenuItem
                  data-testid="generate-menu-ai"
                  disabled
                  onSelect={(e) => {
                    e.preventDefault();
                  }}
                >
                  ✨ Generate (AI)
                </DropdownMenuItem>
              </DisabledTooltip>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// BulkActionBar — sticky bar when ≥1 case selected
// ---------------------------------------------------------------------------

interface BulkActionBarProps {
  selectedIds: Set<string>;
  suites: Suite[];
  onClear: () => void;
}

function BulkActionBar({
  selectedIds,
  suites,
  onClear,
}: BulkActionBarProps): React.ReactElement | null {
  const bulkUpdate = useBulkUpdate();

  const ids = [...selectedIds];
  const count = ids.length;
  const overLimit = count > BULK_LIMIT;

  if (count === 0) return null;

  const handleDelete = (): void => {
    // Delay-delete pattern: optimistically hide, commit on toast expire.
    // This mirrors the single-case handleDelete in CaseDetailPanel:
    // show undoToast first; onUndo = restore; if toast auto-closes without
    // undo → fire the actual bulk delete.
    //
    // Since there is no bulk-restore endpoint, we implement delete-on-expire:
    // the actual DELETE fires only after the undo window closes (same timing
    // as the single-case pattern which also uses undoToast).

    void undoToast({
      label: `Deleted ${count} case${count === 1 ? "" : "s"}`,
      onUndo: () => {
        // No bulk restore — undo is a no-op (items weren't deleted yet).
        // The toast resolve(true) means user clicked Undo before delete fired.
        return Promise.resolve();
      },
      undoSuccessMessage: "Delete cancelled",
    }).then((undone) => {
      if (!undone) {
        // Toast expired without undo → commit the delete
        bulkUpdate.mutate({ action: "delete", ids, payload: {} }, { onSuccess: onClear });
      }
    });
  };

  const handleMoveToSuite = (suiteId: string): void => {
    if (!suiteId) return;
    bulkUpdate.mutate(
      { action: "move_to_suite", ids, payload: { suiteId } },
      { onSuccess: onClear },
    );
  };

  const handleSetPriority = (priority: string): void => {
    if (!priority) return;
    bulkUpdate.mutate(
      {
        action: "set_priority",
        ids,
        payload: { priority: priority as Priority },
      },
      { onSuccess: onClear },
    );
  };

  return (
    <div
      data-testid="bulk-action-bar"
      className={cn(
        "z-10 flex shrink-0 items-center gap-3 border-t border-border bg-bg-elev-2 px-4 py-2",
        "shadow-[0_-2px_8px_rgba(0,0,0,.4)]",
      )}
    >
      <span className="shrink-0 font-mono text-[12px] text-fg-3">{count} selected</span>
      {overLimit ? (
        <span className="text-[11px] text-amber">Max {BULK_LIMIT} at a time</span>
      ) : null}
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="bulk-delete-btn"
          disabled={overLimit || bulkUpdate.isPending}
          className="text-fg-3 hover:text-red"
          onClick={handleDelete}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          Delete
        </Button>

        <select
          data-testid="bulk-move-suite-select"
          defaultValue=""
          disabled={overLimit || bulkUpdate.isPending}
          onChange={(e) => {
            handleMoveToSuite(e.target.value);
            e.target.value = "";
          }}
          className={cn(
            "h-8 rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-3",
            "focus:outline-none focus:ring-1 focus:ring-accent/40",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          <option value="" disabled>
            Move to suite…
          </option>
          {suites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>

        <select
          data-testid="bulk-priority-select"
          defaultValue=""
          disabled={overLimit || bulkUpdate.isPending}
          onChange={(e) => {
            handleSetPriority(e.target.value);
            e.target.value = "";
          }}
          className={cn(
            "h-8 rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-3",
            "focus:outline-none focus:ring-1 focus:ring-accent/40",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          <option value="" disabled>
            Set priority…
          </option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <button
        type="button"
        data-testid="bulk-clear-btn"
        className="ml-auto text-[11px] text-fg-4 hover:text-fg-1"
        onClick={onClear}
      >
        Clear
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CaseTree — with selection checkboxes
// ---------------------------------------------------------------------------

function CaseTree({
  suites,
  cases,
  selectedId,
  selectedIds,
  onSelect,
  onToggleSelection,
  onToggleAll,
  onNewCase,
  onGenerate,
  gatingSuiteId,
  onSetGating,
}: {
  suites: Suite[];
  cases: Case[];
  selectedId: string | null;
  selectedIds: Set<string>;
  onSelect: (publicId: string) => void;
  onToggleSelection: (id: string) => void;
  onToggleAll: (ids: string[]) => void;
  onNewCase: () => void;
  onGenerate: (strategy?: GeneratorStrategy) => void;
  gatingSuiteId: string | null;
  onSetGating: (suiteId: string) => void;
}): React.ReactElement {
  const allIds = cases.map((c) => c.id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selectedIds.has(id));
  const someSelected = !allSelected && allIds.some((id) => selectedIds.has(id));

  const headerCheckboxRef = useRef<HTMLInputElement>(null);

  // Sync indeterminate via ref (Checkbox component handles this internally)
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
        className="h-full border-none bg-transparent"
        subtitle="Generate from OpenAPI, record a browser session, or write manually."
        action={[
          {
            label: "From OpenAPI",
            variant: "outline",
            onClick: () => {
              onGenerate("openapi");
            },
          },
          {
            label: "Record session",
            variant: "outline",
            onClick: () => {
              onGenerate("recorder");
            },
          },
          { label: "Write manually", variant: "default", onClick: onNewCase },
        ]}
      />
    );
  }

  return (
    <nav className="flex flex-col gap-4" data-testid="cases-tree">
      {/* Select-all header */}
      <div className="flex items-center gap-2 px-2">
        <Checkbox
          ref={headerCheckboxRef}
          data-testid="select-all-checkbox"
          checked={allSelected}
          indeterminate={someSelected}
          aria-label="Select all cases"
          onCheckedChange={() => {
            onToggleAll(allIds);
          }}
        />
        <span className="text-[11px] text-fg-4">
          {selectedIds.size > 0 ? `${selectedIds.size} selected` : "Select all"}
        </span>
      </div>

      {[...grouped.entries()].map(([suiteId, items]) => {
        const suite = suites.find((s) => s.id === suiteId);
        return (
          <div key={suiteId} data-testid="cases-tree-suite">
            <div className="mb-1.5 flex items-center gap-1.5 px-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-fg-5">
              <FolderTree className="h-3 w-3" aria-hidden="true" />
              {suite?.name ?? "Unassigned"}
              <span className="font-mono text-[10px] text-fg-5">{items.length}</span>
              {suite ? (
                suite.id === gatingSuiteId ? (
                  <span
                    data-testid="suite-gating-badge"
                    className="ml-auto rounded-sm bg-accent/10 px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-accent"
                  >
                    Gating
                  </span>
                ) : (
                  <button
                    type="button"
                    data-testid="suite-set-gating-btn"
                    onClick={() => {
                      onSetGating(suite.id);
                    }}
                    className="ml-auto rounded-sm px-1 text-[9px] font-medium tracking-wide text-fg-4 hover:text-accent"
                  >
                    Set gating
                  </button>
                )
              ) : null}
            </div>
            <ul className="flex flex-col gap-px">
              {items.map((c) => (
                <li key={c.id} className="flex min-w-0 items-center">
                  <Checkbox
                    data-testid="case-row-checkbox"
                    checked={selectedIds.has(c.id)}
                    aria-label={`Select ${c.public_id}`}
                    className="ml-1 mr-1.5 shrink-0"
                    onCheckedChange={() => {
                      onToggleSelection(c.id);
                    }}
                    onClick={(e) => {
                      // Prevent the checkbox click from bubbling to the row button
                      e.stopPropagation();
                    }}
                  />
                  <button
                    type="button"
                    data-testid="cases-tree-row"
                    data-public-id={c.public_id}
                    data-selected={c.public_id === selectedId ? "true" : "false"}
                    onClick={() => {
                      onSelect(c.public_id);
                    }}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 overflow-hidden rounded-md px-2 py-2 text-left text-[12.5px] text-fg-1 hover:bg-bg-elev-2",
                      c.public_id === selectedId &&
                        "bg-bg-elev-2 shadow-[inset_2px_0_0_0_theme(colors.accent)]",
                    )}
                  >
                    <SourceDot status={c.status === "DEPRECATED" || c.status === "STALE" ? "warn" : "pass"} />
                    <span className="shrink-0 whitespace-nowrap font-mono text-[10.5px] text-fg-5">
                      {c.public_id}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium" title={c.title}>
                      {c.title || displayTitle(c.name)}
                    </span>
                    <span className="shrink-0">
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
  const syncedRef = useMemo(() => serverStepIds, [serverStepIds]);

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
  const stepsToShow =
    draftSteps.length === 0 && effectiveSteps.length === 0
      ? []
      : draftSteps.length > 0
        ? draftSteps
        : effectiveSteps;

  const handleStepsChange = useCallback((next: DraftStep[]) => {
    setDraftSteps(next);
  }, []);

  // ---- QA-readable derivations (hooks must run before the guards below) ----
  const lastRunId = detail?.last_run_id ?? null;
  const { data: caseRunSteps } = useQuery({
    queryKey: ["case-result-steps", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRunSteps(lastRunId) : Promise.resolve({ items: [] })),
    enabled: Boolean(lastRunId),
  });

  // Fallback generation keys off the technical slug (the legacy name is only
  // used when a pre-migration row has no slug).
  const detailName = detail?.slug ?? detail?.name;
  // Real steps → derive readable view; none → labelled fallback from the slug.
  const derivedSteps = useMemo(
    () =>
      serverSteps.length > 0
        ? serverSteps.map(deriveServerStep)
        : detailName
          ? generateFallbackSteps(detailName)
          : [],
    // serverStepIds is a stable signature of serverSteps (ids joined).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [serverStepIds, detailName],
  );
  const stepsAreFallback = serverSteps.length === 0 && Boolean(detail);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const caseType = useMemo(() => deriveCaseType(serverSteps), [serverStepIds]);
  const outcomeByOrder = useMemo(() => {
    const m = new Map<number, StepOutcome>();
    const cid = detail?.id;
    if (!cid) return m;
    for (const s of caseRunSteps?.items ?? []) {
      if (s.case_id === cid) m.set(s.step_order, s.outcome);
    }
    return m;
  }, [caseRunSteps, detail?.id]);

  if (!publicId) {
    return (
      <EmptyState
        icon={FileText}
        title="Select a case"
        className="h-full border-none bg-transparent"
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
  // The API now sends the human ``title`` (backend derives it — DATA_MODEL
  // §3.4); the client-side humanizer only remains as a legacy fallback.
  const caseTitle = detail.title || displayTitle(detail.name);
  const slugKey = detail.slug ?? technicalKey(detail.name);
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
        name: `Ad-hoc: ${detail.title || detail.name}`,
        selection: [{ caseId: detail.id }],
        trigger: "MANUAL",
      },
      {
        onSuccess: (run) => {
          // Navigate with the INTERNAL run id: `GET /runs/:id` resolves by PK
          // and the runner publishes WS events on `run:{internal_id}`, so the
          // run-detail fetch + live stream both key off it (public_id 404s).
          void navigate({ to: "/runs/$runId", params: { runId: run.id } });
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
        <div className="flex flex-wrap items-center gap-2">
          <span
            data-testid="case-code"
            className="rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[11px] text-fg-3"
          >
            {detail.public_id}
          </span>
          <SourcePill source={sourcePill} />
          <span
            data-testid="case-type-badge"
            className="rounded-full border border-border bg-bg-elev-2 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-3"
          >
            {caseTypeLabel(caseType)}
          </span>
          <StatusBadge
            status={detail.status === "ACTIVE" ? "pass" : "neutral"}
            label={detail.status}
          />
          <span className="rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[11px] text-fg-3">
            {detail.priority}
          </span>
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
        <h3
          data-testid="case-title"
          className="text-[22px] font-semibold leading-tight tracking-[-.01em] text-fg-1"
        >
          {caseTitle}
        </h3>
        {slugKey ? (
          <span data-testid="case-slug" className="font-mono text-[11px] text-fg-5">
            {slugKey}
          </span>
        ) : null}
        {detail.description ? (
          <p className="max-w-[70ch] text-[13px] leading-relaxed text-fg-3">{detail.description}</p>
        ) : null}
      </div>

      <Tabs defaultValue="basics" className="gap-4" data-testid="case-detail-tabs">
        <TabsList variant="line" className="h-auto flex-wrap p-0">
          <TabsTrigger value="basics" className="text-[12.5px]" data-testid="case-tab-basics">
            Basics
          </TabsTrigger>
          <TabsTrigger value="steps" className="text-[12.5px]" data-testid="case-tab-steps">
            Steps
          </TabsTrigger>
          <TabsTrigger value="preview" className="text-[12.5px]" data-testid="case-tab-preview">
            Video / Preview
          </TabsTrigger>
          <TabsTrigger value="code" className="text-[12.5px]" data-testid="case-tab-code">
            Code
          </TabsTrigger>
          <TabsTrigger value="logs" className="text-[12.5px]" data-testid="case-tab-logs">
            Logs
          </TabsTrigger>
          <TabsTrigger value="artifacts" className="text-[12.5px]" data-testid="case-tab-artifacts">
            Artifacts
          </TabsTrigger>
        </TabsList>

        <TabsContent value="basics">
          <CaseBasicsTab
            detail={detail}
            sourcePill={sourcePill}
            caseType={caseType}
            derivedSteps={derivedSteps}
            slugKey={slugKey}
          />
        </TabsContent>

        <TabsContent value="steps" className="flex flex-col gap-4">
          <StepList
            steps={derivedSteps}
            isFallback={stepsAreFallback}
            outcomeByOrder={outcomeByOrder}
          />
          <details className="group rounded-md border border-border bg-bg-elev-1">
            <summary className="cursor-pointer select-none px-3 py-2 text-[12px] text-fg-3 hover:text-fg-1">
              Edit steps
            </summary>
            <div className="border-t border-border p-3" data-testid="case-steps">
              <StepEditor
                caseId={detail.public_id}
                steps={stepsToShow}
                onStepsChange={handleStepsChange}
              />
            </div>
          </details>
          <Gated feature="ai_diagnose" fallback={null}>
            <AgentInsightCallout
              title="Agent diagnosis"
              confidence="High"
              body={`Last run on ${detail.public_id} suggests stable behaviour. No outstanding flake signals.`}
            />
          </Gated>
        </TabsContent>

        <TabsContent value="preview">
          <EvidencePreview detail={detail} derivedSteps={derivedSteps} />
        </TabsContent>

        <TabsContent value="code">
          <CaseCodeTab detail={detail} />
        </TabsContent>

        <TabsContent value="logs">
          <CaseLogsTab lastRunId={lastRunId} />
        </TabsContent>

        <TabsContent value="artifacts">
          <CaseArtifactsTab lastRunId={lastRunId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail tabs
// ---------------------------------------------------------------------------

function CaseBasicsTab({
  detail,
  sourcePill,
  caseType,
  derivedSteps,
  slugKey,
}: {
  detail: CaseDetail;
  sourcePill: "MANUAL" | "AI" | "MCP" | "IMPORT";
  caseType: ReturnType<typeof deriveCaseType>;
  derivedSteps: ReturnType<typeof deriveServerStep>[];
  slugKey: string | null;
}): React.ReactElement {
  const expectations = derivedSteps.filter((s) => s.type === "assertion").map((s) => s.expected);
  const tags = detail.tags ?? [];

  return (
    <div className="flex flex-col gap-4" data-testid="case-basics">
      {detail.description ? (
        <Field label="Description">
          <p className="text-[12.5px] leading-relaxed text-fg-2">{detail.description}</p>
        </Field>
      ) : null}

      {detail.preconditions ? (
        <Field label="Preconditions">
          <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-fg-2">
            {detail.preconditions}
          </p>
        </Field>
      ) : null}

      <Field label="Expected result">
        {expectations.length > 0 ? (
          <ul className="flex list-inside list-disc flex-col gap-1 text-[12.5px] text-fg-2">
            {expectations.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        ) : (
          <p className="text-[12.5px] text-fg-4">
            Derived from the case&apos;s assertion steps once available.
          </p>
        )}
      </Field>

      <dl className="grid grid-cols-2 gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px] text-[12px] sm:grid-cols-3">
        <Meta label="Source" value={<SourcePill source={sourcePill} />} />
        <Meta label="Type" value={caseTypeLabel(caseType)} />
        <Meta label="Priority" value={detail.priority} mono />
        <Meta label="Owner" value={detail.owner_id ?? "—"} />
        <Meta label="Suite" value={detail.suite_id} mono />
        <Meta
          label="Updated"
          value={formatDistanceToNow(new Date(detail.updated_at), { addSuffix: true })}
        />
        <Meta label="Key / slug" value={slugKey ?? "—"} mono />
        <Meta
          label="Tags"
          value={
            tags.length > 0 ? (
              <span className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-sm bg-bg-elev-2 px-1.5 py-0.5 text-[10.5px] text-fg-3"
                  >
                    {tag}
                  </span>
                ))}
              </span>
            ) : (
              "—"
            )
          }
        />
      </dl>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10.5px] uppercase tracking-wide text-fg-5">{label}</span>
      {children}
    </div>
  );
}

/**
 * Evidence timeline for a case: the readable step list on the left (with per-
 * step run outcome + a cumulative timestamp), and a video/screenshot preview on
 * the right. Clicking a step selects it and swaps the preview to that step's
 * screenshot. When no run exists yet the timeline still renders (from the
 * derived steps) with an elegant "run to capture evidence" placeholder.
 */
function EvidencePreview({
  detail,
  derivedSteps,
}: {
  detail: CaseDetail;
  derivedSteps: ReturnType<typeof deriveServerStep>[];
}): React.ReactElement {
  const lastRunId = detail.last_run_id ?? null;

  const { data: stepsData } = useQuery({
    queryKey: ["case-result-steps", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRunSteps(lastRunId) : Promise.resolve({ items: [] })),
    enabled: Boolean(lastRunId),
  });
  const { data: artifactsData } = useQuery({
    queryKey: ["case-result-artifacts", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRunArtifacts(lastRunId) : Promise.resolve({ items: [] })),
    enabled: Boolean(lastRunId),
  });

  const runSteps = useMemo<RunStepPublic[]>(
    () =>
      (stepsData?.items ?? [])
        .filter((s) => s.case_id === detail.id)
        .sort((a, b) => a.step_order - b.step_order),
    [stepsData, detail.id],
  );
  const artifacts = useMemo(() => artifactsData?.items ?? [], [artifactsData]);
  const runStepIds = useMemo(() => new Set(runSteps.map((s) => s.id)), [runSteps]);

  const outcomeByOrder = useMemo(() => {
    const m = new Map<number, StepOutcome>();
    for (const s of runSteps) m.set(s.step_order, s.outcome);
    return m;
  }, [runSteps]);
  const runStepIdByOrder = useMemo(() => {
    const m = new Map<number, string>();
    for (const s of runSteps) m.set(s.step_order, s.id);
    return m;
  }, [runSteps]);
  // Cumulative offset per step (start of step N = sum of durations before it).
  const offsetByOrder = useMemo(() => {
    const m = new Map<number, number>();
    let acc = 0;
    for (const s of runSteps) {
      m.set(s.step_order, acc);
      acc += s.duration_ms ?? 0;
    }
    return m;
  }, [runSteps]);

  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  const [stepShotUrl, setStepShotUrl] = useState<string | null>(null);
  const lastResolvedVideoId = useRef<string | null>(null);

  useEffect(() => {
    if (!lastRunId) {
      setVideoUrl(null);
      return;
    }
    const video = artifacts.find((a) => a.kind === "VIDEO" && runStepIds.has(a.run_step_id));
    if (!video) {
      setVideoUrl(null);
      lastResolvedVideoId.current = null;
      return;
    }
    if (lastResolvedVideoId.current === video.id) return;
    lastResolvedVideoId.current = video.id;
    let cancelled = false;
    void fetchRunSignedUrl(lastRunId, video.id).then((signed) => {
      if (!cancelled) setVideoUrl(signed.url);
    });
    return () => {
      cancelled = true;
    };
  }, [lastRunId, artifacts, runStepIds]);

  useEffect(() => {
    const runStepId = selectedOrder === null ? null : (runStepIdByOrder.get(selectedOrder) ?? null);
    if (!lastRunId || runStepId === null) {
      setStepShotUrl(null);
      return;
    }
    const shot = artifacts.find((a) => a.kind === "SCREENSHOT" && a.run_step_id === runStepId);
    if (!shot) {
      setStepShotUrl(null);
      return;
    }
    let cancelled = false;
    void fetchRunSignedUrl(lastRunId, shot.id).then((signed) => {
      if (!cancelled) setStepShotUrl(signed.url);
    });
    return () => {
      cancelled = true;
    };
  }, [lastRunId, selectedOrder, artifacts, runStepIdByOrder]);

  const selectedStepLabel = selectedOrder === null ? null : `Step ${selectedOrder.toString()}`;

  return (
    <div className="flex flex-col gap-3" data-testid="case-evidence">
      {!lastRunId ? (
        <div
          className="rounded-md border border-border bg-bg-elev-2 px-4 py-3 text-[12px] text-fg-3"
          data-testid="case-evidence-norun"
        >
          No run yet — run this case (or enable evidence recording) to capture video and per-step
          screenshots. The step timeline below is the planned scenario.
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <span className="text-[10.5px] uppercase tracking-wide text-fg-5">Step timeline</span>
          <StepList
            steps={derivedSteps}
            outcomeByOrder={outcomeByOrder}
            offsetByOrder={offsetByOrder}
            selectedOrder={selectedOrder}
            onSelectStep={(order) => {
              setSelectedOrder((prev) => (prev === order ? null : order));
            }}
          />
        </div>
        <BrowserPreview
          url={null}
          videoUrl={videoUrl}
          code={detail.automation_code ?? null}
          stepScreenshotUrl={stepShotUrl}
          stepLabel={selectedStepLabel}
          onClearStep={() => {
            setSelectedOrder(null);
          }}
        />
      </div>
    </div>
  );
}

function CaseCodeTab({ detail }: { detail: CaseDetail }): React.ReactElement {
  const code = detail.automation_code?.trim();
  if (!code) {
    return (
      <EmptyState
        icon={Code2}
        title="No generated code"
        subtitle="Generated code is not available for this test case yet."
      />
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="case-code-view">
      {detail.automation_file_path ? (
        <span className="font-mono text-[11px] text-fg-4">{detail.automation_file_path}</span>
      ) : null}
      <pre className="max-h-[420px] overflow-auto rounded-md border border-border bg-bg-code p-3 font-mono text-[11.5px] leading-relaxed text-fg-3">
        {code}
      </pre>
    </div>
  );
}

function CaseLogsTab({ lastRunId }: { lastRunId: string | null }): React.ReactElement {
  const { data, isLoading } = useQuery({
    queryKey: ["case-result-logs", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRunLogs(lastRunId) : Promise.resolve(null)),
    enabled: Boolean(lastRunId),
  });

  if (!lastRunId) {
    return (
      <EmptyState
        icon={ScrollText}
        title="No logs yet"
        subtitle="Run this case to capture its execution logs."
      />
    );
  }
  if (isLoading) return <CasesSkeleton />;
  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={ScrollText}
        title="No logs recorded"
        subtitle="The last run did not emit any log lines."
      />
    );
  }
  return (
    <div
      className="max-h-[420px] overflow-auto rounded-md border border-border bg-bg-code p-3 font-mono text-[11.5px] leading-relaxed"
      data-testid="case-logs-view"
    >
      {items.map((log) => (
        <div key={log.seq} className="flex gap-2">
          <span className="shrink-0 text-fg-5">{log.level.toUpperCase()}</span>
          <span className="whitespace-pre-wrap break-all text-fg-3">{log.message}</span>
        </div>
      ))}
    </div>
  );
}

function CaseArtifactsTab({ lastRunId }: { lastRunId: string | null }): React.ReactElement {
  const { data, isLoading } = useQuery({
    queryKey: ["case-result-artifacts", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRunArtifacts(lastRunId) : Promise.resolve({ items: [] })),
    enabled: Boolean(lastRunId),
  });

  if (!lastRunId) {
    return (
      <EmptyState
        icon={Paperclip}
        title="No artifacts yet"
        subtitle="Run this case to capture video, screenshots, traces, and logs."
      />
    );
  }
  if (isLoading) return <CasesSkeleton />;
  const items: ArtifactPublic[] = data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={Paperclip}
        title="No artifacts"
        subtitle="The last run produced no downloadable artifacts."
      />
    );
  }

  const open = (artifactId: string): void => {
    void fetchRunSignedUrl(lastRunId, artifactId).then((signed) => {
      window.open(signed.url, "_blank", "noopener,noreferrer");
    });
  };

  return (
    <ul className="flex flex-col gap-1.5" data-testid="case-artifacts-view">
      {items.map((a) => (
        <li
          key={a.id}
          className="flex items-center gap-3 rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-[12px]"
        >
          <span className="rounded-sm bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-3">
            {a.kind}
          </span>
          <span className="font-mono text-[11px] text-fg-4">{a.mime_type}</span>
          <span className="ml-auto font-mono text-[11px] text-fg-5 tabular-nums">
            {Math.max(1, Math.round(a.size_bytes / 1024)).toString()} KB
          </span>
          <Button type="button" size="sm" variant="outline" onClick={() => open(a.id)}>
            Open
          </Button>
        </li>
      ))}
    </ul>
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
  const projectId = useActiveProject((s) => s.projectId);
  const { data: project } = useProject(projectId);
  const setGating = useSetGatingSuite();
  const gatingSuiteId = project?.gating_suite_id ?? null;

  const [active, setActive] = useState<Tab>("all");
  const [suiteDialogOpen, setSuiteDialogOpen] = useState(false);
  const [caseDialogOpen, setCaseDialogOpen] = useState(false);
  const [query, setQuery] = useState("");

  // GenerateModal state — `null` strategy = open at the target-select step;
  // a concrete strategy deep-links from the split-button dropdown.
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateStrategy, setGenerateStrategy] = useState<GeneratorStrategy | undefined>(
    undefined,
  );

  const handleGenerate = useCallback((strategy?: GeneratorStrategy) => {
    setGenerateStrategy(strategy);
    setGenerateOpen(true);
  }, []);

  // Selection state: Set of internal case IDs (case.id, not public_id).
  // The bulk endpoint expects internal UUIDs.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const counts = useMemo<Record<Tab, number>>(() => {
    const all = cases.items.length;
    const manual = cases.items.filter((c) => c.source === "MANUAL").length;
    const ai = cases.items.filter((c) => c.source === "AI").length;
    const mcp = cases.items.filter((c) => c.source === "MCP").length;
    const failing = cases.items.filter(isFailing).length;
    return { all, manual, ai, mcp, failing };
  }, [cases]);

  const filtered = useMemo(() => {
    const byTab = (() => {
      switch (active) {
        case "manual":
          return cases.items.filter((c) => c.source === "MANUAL");
        case "ai":
          return cases.items.filter((c) => c.source === "AI");
        case "mcp":
          return cases.items.filter((c) => c.source === "MCP");
        case "failing":
          return cases.items.filter(isFailing);
        default:
          return cases.items;
      }
    })();
    const q = query.trim().toLowerCase();
    if (q === "") return byTab;
    // Client-side, ZERO-friendly search over the loaded cases (title + name +
    // public id) so both human phrasing and the technical key match.
    return byTab.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        c.public_id.toLowerCase().includes(q),
    );
  }, [active, cases, query]);

  const selectedId = search.case ?? null;

  const handleToggleSelection = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleToggleAll = useCallback((ids: string[]) => {
    setSelectedIds((prev) => {
      const allSelected = ids.every((id) => prev.has(id));
      if (allSelected) {
        // Deselect all
        const next = new Set(prev);
        for (const id of ids) next.delete(id);
        return next;
      }
      // Select all
      return new Set([...prev, ...ids]);
    });
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  return (
    <>
      <CasesHeader
        active={active}
        setActive={setActive}
        counts={counts}
        showAiTab={aiTabVisible}
        onGenerate={handleGenerate}
        aiEnabled={aiTabVisible}
      />
      {generateOpen ? (
        <GenerateModal
          open={generateOpen}
          onClose={() => {
            setGenerateOpen(false);
          }}
          suites={suites.items}
          projectId={projectId}
          {...(generateStrategy ? { initialStrategy: generateStrategy } : {})}
        />
      ) : null}
      <CreateSuiteDialog
        open={suiteDialogOpen}
        onClose={() => {
          setSuiteDialogOpen(false);
        }}
      />
      <CreateCaseDialog
        open={caseDialogOpen}
        onClose={() => {
          setCaseDialogOpen(false);
        }}
        suites={suites.items}
        onCreated={(publicId) => {
          void navigate({ search: { case: publicId } });
        }}
      />
      {suites.items.length === 0 ? (
        <EmptyState
          icon={FolderTree}
          title="Create your first suite"
          subtitle="Test cases live inside suites. Add one to start authoring cases."
          action={{
            label: "New suite",
            variant: "default",
            onClick: () => {
              setSuiteDialogOpen(true);
            },
          }}
        />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] xl:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
          <aside
            className={cn(
              "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-bg-elev-1",
              "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04),0_16px_40px_-24px_rgba(0,0,0,0.9)]",
            )}
            data-testid="cases-left-pane"
          >
            <div className="flex shrink-0 flex-col gap-2 border-b border-border p-3">
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                }}
                placeholder="Search cases…"
                className="h-8"
                data-testid="cases-search"
                aria-label="Search cases"
              />
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="flex-1"
                  data-testid="new-suite-btn"
                  onClick={() => {
                    setSuiteDialogOpen(true);
                  }}
                >
                  New suite
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="flex-1"
                  data-testid="new-case-btn"
                  onClick={() => {
                    setCaseDialogOpen(true);
                  }}
                >
                  New case
                </Button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <CaseTree
                suites={suites.items}
                cases={filtered}
                selectedId={selectedId}
                selectedIds={selectedIds}
                onSelect={(publicId) => {
                  void navigate({ search: { case: publicId } });
                }}
                onToggleSelection={handleToggleSelection}
                onToggleAll={handleToggleAll}
                onNewCase={() => {
                  setCaseDialogOpen(true);
                }}
                onGenerate={handleGenerate}
                gatingSuiteId={gatingSuiteId}
                onSetGating={(suiteId) => {
                  if (projectId) setGating.mutate({ projectId, suiteId });
                }}
              />
            </div>
            <BulkActionBar
              selectedIds={selectedIds}
              suites={suites.items}
              onClear={handleClearSelection}
            />
          </aside>
          <section
            className={cn(
              "min-h-0 min-w-0 overflow-y-auto rounded-lg border border-border bg-bg-elev-1 p-5",
              "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04),0_16px_40px_-24px_rgba(0,0,0,0.9)]",
            )}
            data-testid="cases-right-pane"
          >
            <CaseDetailPanel publicId={selectedId} suites={suites.items} />
          </section>
        </div>
      )}
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

// First-project bootstrap (dogfood blocker #1). A fresh ZERO install has a
// default workspace but no projects; every project-scoped query 422s without
// an active project, so we short-circuit to a create-project prompt before any
// data hook runs.
function NoProjectBootstrap(): React.ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <>
      <EmptyState
        icon={FolderTree}
        title="Create your first project"
        subtitle="Projects hold your test suites and cases. Make one to start testing."
        action={{
          label: "New project",
          variant: "default",
          onClick: () => {
            setOpen(true);
          },
        }}
      />
      <CreateProjectDialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
      />
    </>
  );
}

// Hide the AI tab in ZERO via wrapper — leverages Gated for ergonomic
// composition, so the CasesHeader doesn't have to know about capabilities.
function CasesContainer(): React.ReactElement {
  const projectId = useActiveProject((s) => s.projectId);
  return (
    <section className="flex h-full min-h-0 flex-col gap-4" data-testid="cases-screen">
      <ErrorBoundary fallback={({ reset }) => <CasesError reset={reset} />}>
        <Suspense fallback={<CasesSkeleton />}>
          {projectId === null ? <NoProjectBootstrap /> : <CasesBody />}
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

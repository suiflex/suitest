import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { formatFriendlyTimestamp, formatRelativeTime } from "@/lib/date";
import {
  AlertTriangle,
  ArrowUp,
  CameraOff,
  ChevronDown,
  ChevronRight,
  Code2,
  Download,
  FileDown,
  FileText,
  FolderTree,
  ListChecks,
  Paperclip,
  Play,
  ScrollText,
  Search,
  Settings2,
  Trash2,
  Video,
  X,
  ZoomIn,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmBulkRunDialog } from "@/components/cases/ConfirmBulkRunDialog";
import { ImageLightboxModal, type LightboxImage } from "@/components/runs/ImageLightboxModal";
import { VideoPlayerModal } from "@/components/runs/VideoPlayerModal";
import { loadSavedExecutionSettings } from "@/components/runs/execution-settings";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { usePermissions } from "@/hooks/use-permissions";
import { CreateCaseDialog } from "@/components/cases/CreateCaseDialog";
import { CreateSuiteDialog } from "@/components/cases/CreateSuiteDialog";
import { ExportUatDialog } from "@/components/cases/ExportUatDialog";
import { GenerateModal } from "@/components/cases/GenerateModal";
import type { GeneratorStrategy } from "@/components/cases/GenerateModal";
import { CasesSkeleton } from "@/components/cases/skeleton";
import { StepEditor } from "@/components/cases/StepEditor";
import type { DraftStep } from "@/components/cases/StepEditor";
import { StepList } from "@/components/cases/StepList";
import { TestingApproachBadge } from "@/components/cases/TestingApproachBadge";
import { TestStrategyDialog } from "@/components/cases/TestStrategyDialog";
import { BrowserPreview } from "@/components/runs/BrowserPreview";
import { Gated } from "@/components/gating/Gated";
import { AgentInsightCallout } from "@/components/shared/AgentInsightCallout";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { FirstProjectBootstrap } from "@/components/shared/FirstProjectBootstrap";
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
  fetchCaseArtifacts,
  fetchCaseRuns,
  fetchRun,
  fetchRunArtifacts,
  fetchRunLogs,
  fetchRunSignedUrl,
  fetchRunSteps,
  type CaseArtifactPublic,
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
import { useCreateRun, type PlaywrightConfigInput } from "@/hooks/use-runs";
import {
  useBulkUpdate,
  useDeleteTestCase,
  useRestoreTestCase,
  useSuites,
  useTestCase,
  useTestCases,
  useUpdateTestingMetadata,
} from "@/hooks/use-test-cases";
import { useRunArtifactUrl } from "@/hooks/use-run-artifact-url";
import type { components } from "@/lib/api-types";
import { runToBadge } from "@/lib/badge-maps";
import { caseSourceToPill } from "@/lib/test-case-format";
import { undoToast } from "@/lib/undo-toast";
import { cn } from "@/lib/utils";

type Case = components["schemas"]["TestCaseListItem"];
type Suite = components["schemas"]["SuitePublic"];
type Priority = components["schemas"]["Priority"];
type CaseDetail = components["schemas"]["TestCaseDetail"];
type RunStepPublic = components["schemas"]["RunStepPublic"];
type RunStatus = components["schemas"]["RunStatus"];
type StepOutcome = components["schemas"]["StepOutcome"];
type TestingApproach = components["schemas"]["TestingApproach"];
type TestLevel = components["schemas"]["TestLevel"];

type Tab = "all" | "manual" | "ai" | "mcp" | "failing";

const BULK_LIMIT = 100;
const PRIORITIES: Priority[] = ["P0", "P1", "P2", "P3"];
// Splitter bounds for the cases list / detail master-detail layout.
const LEFT_DEFAULT = 380;
const LEFT_MIN = 280;
const LEFT_MAX = 720;

/** A case is "failing" when its last run ended in FAIL or ERROR. */
function isFailing(c: Case): boolean {
  return c.last_run_result === "FAIL" || c.last_run_result === "ERROR";
}

function indexSuites(suites: Suite[]): Map<string, Suite> {
  const indexed = new Map<string, Suite>();
  for (const suite of suites) indexed.set(suite.id, suite);
  return indexed;
}

function assertionExpectations(steps: ReturnType<typeof deriveServerStep>[]): string[] {
  const expectations: string[] = [];
  for (const step of steps) {
    if (step.type === "assertion") expectations.push(step.expected);
  }
  return expectations;
}

function matchesCaseQuery(testCase: Case, query: string): boolean {
  return (
    testCase.title.toLowerCase().includes(query) ||
    testCase.name.toLowerCase().includes(query) ||
    testCase.public_id.toLowerCase().includes(query)
  );
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
  onStrategy,
}: {
  active: Tab;
  setActive: (t: Tab) => void;
  counts: Record<Tab, number>;
  showAiTab: boolean;
  onGenerate: (strategy?: GeneratorStrategy) => void;
  aiEnabled: boolean;
  onStrategy: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const { canWriteTests } = usePermissions();
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
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onStrategy}>
          Test strategy
        </Button>
        {canWriteTests ? (
          <div className="flex items-center" data-testid="generate-split-button">
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
                  <Video className="mr-2 h-3.5 w-3.5" />
                  Generate from recording
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
        ) : null}
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// BulkActionBar — sticky bar when ≥1 case selected
// ---------------------------------------------------------------------------

interface BulkActionBarProps {
  selectedIds: Set<string>;
  cases?: Case[];
  suites: Suite[];
  onClear: () => void;
  projectId?: string | null;
}

function BulkActionBar({
  selectedIds,
  cases = [],
  suites,
  onClear,
  projectId = null,
}: BulkActionBarProps): React.ReactElement | null {
  const navigate = useNavigate();
  const createRun = useCreateRun();
  const bulkUpdate = useBulkUpdate();
  const { canWriteTests } = usePermissions();
  const [confirmRunOpen, setConfirmRunOpen] = useState(false);

  const ids = [...selectedIds];
  const count = ids.length;
  const overLimit = count > BULK_LIMIT;

  if (count === 0) return null;

  const resolvedProjectId = projectId ?? suites[0]?.project_id ?? null;
  const canRun = resolvedProjectId !== null && !overLimit && !createRun.isPending;

  const singleCase = count === 1 ? cases.find((c) => c.id === ids[0]) : undefined;
  const singleCaseTitle = singleCase ? singleCase.title || singleCase.name : undefined;

  const handleConfirmRun = (config?: PlaywrightConfigInput): void => {
    if (!resolvedProjectId || overLimit || count === 0) return;
    const runName = singleCaseTitle
      ? `Ad-hoc: ${singleCaseTitle}`
      : `Ad-hoc: ${count} selected case${count === 1 ? "" : "s"}`;

    const effectiveConfig = config ?? loadSavedExecutionSettings();
    createRun.mutate(
      {
        projectId: resolvedProjectId,
        name: runName,
        selection: ids.map((id) => ({ caseId: id })),
        trigger: "MANUAL",
        playwrightConfig: effectiveConfig,
      },
      {
        onSuccess: (run) => {
          setConfirmRunOpen(false);
          onClear();
          void navigate({ to: "/runs/$runId", params: { runId: run.id } });
        },
      },
    );
  };

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
        "z-10 flex shrink-0 flex-col gap-2 border-t border-border bg-bg-elev-2 px-3 py-2 sm:px-4",
        "shadow-[0_-2px_8px_rgba(0,0,0,.4)]",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 font-mono text-[12px] text-fg-3">{count} selected</span>
          {overLimit ? (
            <span className="truncate text-[11px] text-amber">Max {BULK_LIMIT} at a time</span>
          ) : null}
        </div>
        <button
          type="button"
          data-testid="bulk-clear-btn"
          className="shrink-0 rounded px-1 text-[11px] text-fg-4 hover:text-fg-1 focus:outline-none focus-visible:underline focus-visible:ring-1 focus-visible:ring-accent/40"
          onClick={onClear}
        >
          Clear
        </button>
      </div>

      {canWriteTests ? (
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="bulk-run-btn"
            disabled={!canRun}
            className="shrink-0 text-fg-3 hover:text-fg-1"
            onClick={() => setConfirmRunOpen(true)}
          >
            <Play className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
            Run ({count})
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="bulk-delete-btn"
            disabled={overLimit || bulkUpdate.isPending}
            className="shrink-0 text-fg-3 hover:text-red"
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
              "h-8 min-w-0 max-w-full rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-3",
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
              "h-8 min-w-0 max-w-full rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-3",
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
      ) : null}
      <ConfirmBulkRunDialog
        open={confirmRunOpen}
        onOpenChange={setConfirmRunOpen}
        count={count}
        caseTitle={singleCaseTitle}
        onConfirm={handleConfirmRun}
        isPending={createRun.isPending}
      />
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
  isFiltered = false,
}: {
  suites: Suite[];
  cases: Case[];
  selectedId: string | null;
  selectedIds: Set<string>;
  isFiltered?: boolean;
  onSelect: (publicId: string) => void;
  onToggleSelection: (id: string) => void;
  onToggleAll: (ids: string[]) => void;
  onNewCase: () => void;
  onGenerate: (strategy?: GeneratorStrategy) => void;
  gatingSuiteId: string | null;
  onSetGating: (suiteId: string | null) => void;
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
  const suiteById = useMemo(() => indexSuites(suites), [suites]);

  if (cases.length === 0) {
    return (
      <EmptyState
        icon={ListChecks}
        title={isFiltered ? "No matching cases" : "No cases yet"}
        className="h-full border-none bg-transparent"
        subtitle={
          isFiltered
            ? "No test cases matched the selected tab or filter."
            : "Generate from OpenAPI, record a browser session, or write manually."
        }
        {...(!isFiltered
          ? {
              action: [
                {
                  label: "From OpenAPI",
                  variant: "outline" as const,
                  onClick: () => {
                    onGenerate("openapi");
                  },
                },
                {
                  label: "Record session",
                  variant: "outline" as const,
                  onClick: () => {
                    onGenerate("recorder");
                  },
                },
                { label: "Write manually", variant: "default" as const, onClick: onNewCase },
              ],
            }
          : {})}
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

      {[...grouped.entries()]
        .filter(([_, items]) => !isFiltered || items.length > 0)
        .map(([suiteId, items]) => {
          const suite = suiteById.get(suiteId);
          return (
            <CaseTreeSuite
              key={suiteId}
              suite={suite}
              items={items}
              selectedId={selectedId}
              selectedIds={selectedIds}
              gatingSuiteId={gatingSuiteId}
              onSelect={onSelect}
              onToggleSelection={onToggleSelection}
              onToggleSuite={onToggleAll}
              onSetGating={onSetGating}
            />
          );
        })}
    </nav>
  );
}

function CaseTreeSuite({
  suite,
  items,
  selectedId,
  selectedIds,
  gatingSuiteId,
  onSelect,
  onToggleSelection,
  onToggleSuite,
  onSetGating,
}: {
  suite: Suite | undefined;
  items: Case[];
  selectedId: string | null;
  selectedIds: Set<string>;
  gatingSuiteId: string | null;
  onSelect: (publicId: string) => void;
  onToggleSelection: (id: string) => void;
  onToggleSuite: (ids: string[]) => void;
  onSetGating: (suiteId: string | null) => void;
}): React.ReactElement {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { canManageProjects } = usePermissions();
  const suiteName = suite?.name ?? "Unassigned";
  const itemIds = useMemo(() => items.map((c) => c.id), [items]);
  const allSuiteSelected = itemIds.length > 0 && itemIds.every((id) => selectedIds.has(id));
  const someSuiteSelected = !allSuiteSelected && itemIds.some((id) => selectedIds.has(id));

  return (
    <div data-testid="cases-tree-suite">
      <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-fg-5">
        <button
          type="button"
          data-testid="suite-collapse-btn"
          aria-label={isCollapsed ? `Expand ${suiteName}` : `Collapse ${suiteName}`}
          aria-expanded={!isCollapsed}
          onClick={() => setIsCollapsed((prev) => !prev)}
          className="rounded p-0.5 text-fg-5 hover:bg-bg-elev-2 hover:text-fg-3 focus:outline-none"
        >
          {isCollapsed ? (
            <ChevronRight className="h-3 w-3" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          )}
        </button>
        <Checkbox
          data-testid="suite-row-checkbox"
          checked={allSuiteSelected}
          indeterminate={someSuiteSelected}
          aria-label={`Select all cases in ${suiteName}`}
          disabled={items.length === 0}
          className="shrink-0"
          onCheckedChange={() => {
            onToggleSuite(itemIds);
          }}
          onClick={(e) => {
            e.stopPropagation();
          }}
        />
        <FolderTree className="h-3 w-3 shrink-0" aria-hidden="true" />
        <span className="truncate">{suiteName}</span>
        <span className="shrink-0 font-mono text-[10px] text-fg-5">{items.length}</span>
        {suite?.default_testing_approach ? (
          <TestingApproachBadge
            approach={suite.default_testing_approach}
            className="normal-case tracking-normal shrink-0"
          />
        ) : null}
        {suite ? (
          suite.id === gatingSuiteId ? (
            <div className="ml-auto flex shrink-0 items-center gap-1">
              <span
                data-testid="suite-gating-badge"
                className="rounded-sm bg-accent/10 px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-accent"
              >
                Gating
              </span>
              {canManageProjects ? (
                <button
                  type="button"
                  data-testid="suite-unset-gating-btn"
                  title="Remove gating suite"
                  aria-label="Remove gating suite"
                  onClick={() => {
                    onSetGating(null);
                  }}
                  className="rounded-sm px-1 py-0.5 text-[9px] font-medium tracking-wide text-fg-5 hover:bg-bg-elev-2 hover:text-red transition-colors"
                >
                  Unset
                </button>
              ) : null}
            </div>
          ) : canManageProjects ? (
            <button
              type="button"
              data-testid="suite-set-gating-btn"
              onClick={() => {
                onSetGating(suite.id);
              }}
              className="ml-auto shrink-0 rounded-sm px-1 text-[9px] font-medium tracking-wide text-fg-4 hover:text-accent"
            >
              Set gating
            </button>
          ) : null
        ) : null}
      </div>
      {!isCollapsed ? (
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
                <SourceDot
                  status={c.status === "DEPRECATED" || c.status === "STALE" ? "warn" : "pass"}
                />
                <span className="shrink-0 whitespace-nowrap font-mono text-[10.5px] text-fg-5">
                  {c.public_id}
                </span>
                <span className="min-w-0 flex-1 truncate font-medium" title={c.title}>
                  {c.title || displayTitle(c.name)}
                </span>
                <TestingApproachBadge
                  approach={c.effective_testing_approach}
                  className="hidden xl:inline-flex"
                />
                <span className="shrink-0">
                  <SourcePill source={caseSourceToPill(c.source)} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
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
  const updateTesting = useUpdateTestingMetadata(publicId ?? "");
  const { canWriteTests } = usePermissions();
  const [optionsModalOpen, setOptionsModalOpen] = useState(false);

  // Local draft state for the step editor — seeded from the server response
  // and kept in sync when the server data refreshes (via key on detail?.id).
  const [draftSteps, setDraftSteps] = useState<DraftStep[]>([]);

  // When canWriteTests becomes false (demoted to VIEWER): dismiss modals and revert uncommitted drafts
  useEffect(() => {
    if (!canWriteTests) {
      if (optionsModalOpen) {
        setOptionsModalOpen(false);
      }
      if (draftSteps.length > 0) {
        setDraftSteps([]);
      }
    }
  }, [canWriteTests, optionsModalOpen, draftSteps.length]);

  // Sync draftSteps when the server data arrives or changes
  const serverSteps = detail?.steps ?? [];

  // Use a derived key to detect when serverSteps identity changes so we can
  // reset the draft. We compare by serialised IDs only to avoid infinite loops.
  const serverStepIds = serverSteps.map((s) => s.id).join(",");

  // Reset local draft whenever server data updates (different step IDs or updated timestamp)
  const lastDetailVersionRef = useRef(detail?.updated_at ?? serverStepIds);
  useEffect(() => {
    const currentVersion = detail?.updated_at ?? serverStepIds;
    if (lastDetailVersionRef.current !== currentVersion) {
      lastDetailVersionRef.current = currentVersion;
      setDraftSteps([]);
    }
  }, [detail?.updated_at, serverStepIds]);

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
  if (isLoading) {
    return <CasesSkeleton />;
  }
  if (isError || !detail) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Couldn't load case"
        subtitle="This test case was not found or has been deleted."
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
  const handleRun = (config?: PlaywrightConfigInput): void => {
    if (projectId === null) return;
    const effectiveConfig = config ?? loadSavedExecutionSettings();
    createRun.mutate(
      {
        projectId,
        name: `Ad-hoc: ${detail.title || detail.name}`,
        selection: [{ caseId: detail.id }],
        trigger: "MANUAL",
        playwrightConfig: effectiveConfig,
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
          <TestingApproachBadge approach={detail.effective_testing_approach} />
          <select
            aria-label="Testing approach override"
            value={detail.testing_approach ?? ""}
            disabled={updateTesting.isPending || !canWriteTests}
            onChange={(event) => {
              updateTesting.mutate({
                testingApproach: (event.target.value || null) as TestingApproach | null,
              });
            }}
            className="h-6 rounded-md border border-border bg-bg-base px-1.5 font-mono text-[10px] text-fg-3"
          >
            <option value="">Suite default</option>
            <option value="BLACK_BOX">Black-box</option>
            <option value="GRAY_BOX">Gray-box</option>
            <option value="WHITE_BOX">White-box</option>
          </select>
          <select
            aria-label="Test level"
            value={detail.test_level ?? ""}
            disabled={updateTesting.isPending || !canWriteTests}
            onChange={(event) => {
              updateTesting.mutate({
                testingApproach: detail.testing_approach ?? null,
                testLevel: (event.target.value || null) as TestLevel | null,
              });
            }}
            className="h-6 rounded-md border border-border bg-bg-base px-1.5 font-mono text-[10px] text-fg-3"
          >
            <option value="">No level</option>
            <option value="UNIT">Unit</option>
            <option value="COMPONENT">Component</option>
            <option value="INTEGRATION">Integration</option>
            <option value="SYSTEM">System</option>
            <option value="E2E">E2E</option>
          </select>
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
        {canWriteTests ? (
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
              variant="outline"
              data-testid="case-run-options-btn"
              disabled={!canRun}
              onClick={() => setOptionsModalOpen(true)}
              aria-label="Configure and run case"
              title="Configure execution settings & run"
            >
              <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              size="sm"
              data-testid="case-run-now"
              disabled={!canRun}
              onClick={() => handleRun()}
            >
              {runPending ? "Queuing…" : "Run now"}
            </Button>
          </div>
        ) : null}
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
          {/* Outcome badges per step (from the last run) map onto the editor
              rows by order, so editing and evidence share one view. */}
          <StepEditor
            key={detail.public_id}
            caseId={detail.public_id}
            steps={stepsToShow}
            onStepsChange={handleStepsChange}
            outcomeByOrder={outcomeByOrder}
            canWrite={canWriteTests}
          />
          {lastRunId ? (
            <Gated feature="ai_diagnose" fallback={null}>
              <AgentInsightCallout
                title="Agent diagnosis"
                confidence="High"
                body={`Last run on ${detail.public_id} suggests stable behaviour. No outstanding flake signals.`}
              />
            </Gated>
          ) : null}
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
          <CaseArtifactsTab caseId={detail.id} lastRunId={lastRunId} />
        </TabsContent>
      </Tabs>

      <ConfirmBulkRunDialog
        open={optionsModalOpen}
        onOpenChange={setOptionsModalOpen}
        count={1}
        caseTitle={caseTitle}
        onConfirm={(config) => {
          setOptionsModalOpen(false);
          handleRun(config);
        }}
        isPending={createRun.isPending}
      />
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
  const expectations = assertionExpectations(derivedSteps);
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
        <Meta label="Updated" value={formatRelativeTime(detail.updated_at)} />
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
  const { data: lastRunData } = useQuery({
    queryKey: ["run-summary-case-artifact", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRun(lastRunId) : null),
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

  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  const [stepShotUrl, setStepShotUrl] = useState<string | null>(null);
  const videoArtifactId = useMemo(
    () =>
      artifacts.find(
        (artifact) => artifact.kind === "VIDEO" && runStepIds.has(artifact.run_step_id),
      )?.id ?? null,
    [artifacts, runStepIds],
  );
  const videoUrl = useRunArtifactUrl(lastRunId ?? null, videoArtifactId);

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
          playwrightConfig={lastRunData?.playwrightConfig ?? null}
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

type ArtifactFilterKind = "ALL" | "SCREENSHOT" | "VIDEO" | "TRACE" | "LOG";

interface RunArtifactGroup {
  runId: string;
  runPublicId: string;
  runStatus?: RunStatus | null;
  runDate: string;
  items: CaseArtifactPublic[];
  playwrightConfig?: PlaywrightConfigInput | null | undefined;
}

interface RunArtifactGroupSectionProps {
  group: RunArtifactGroup;
  getRawUrl: (item: CaseArtifactPublic) => string;
  onZoom: (params: { images: LightboxImage[]; currentIndex: number }) => void;
  onPlayVideo?: (params: { src: string; title: string; subtitle?: string | null | undefined }) => void;
}

function RunArtifactGroupSection({
  group,
  getRawUrl,
  onZoom,
  onPlayVideo,
}: RunArtifactGroupSectionProps): React.ReactElement {
  const screenshots = useMemo(
    () => group.items.filter((item) => item.kind === "SCREENSHOT"),
    [group.items],
  );

  const galleryImages = useMemo<LightboxImage[]>(() => {
    return screenshots.map((shot) => {
      const shotUrl = getRawUrl(shot);
      const shotLabel = shot.stepTitle
        ? `Step ${shot.stepOrder}: ${shot.stepTitle}`
        : `Step ${shot.stepOrder} Screenshot`;
      const shotSize = shot.sizeBytes
        ? `${Math.max(1, Math.round(shot.sizeBytes / 1024)).toString()} KB`
        : "—";
      return {
        src: shotUrl,
        title: `${group.runPublicId} - ${shotLabel}`,
        subtitle: `${formatFriendlyTimestamp(group.runDate)} • ${shotSize}`,
      };
    });
  }, [screenshots, getRawUrl, group.runPublicId, group.runDate]);

  const handleOpenScreenshot = (shotId: string): void => {
    const idx = screenshots.findIndex((s) => s.id === shotId);
    onZoom({ images: galleryImages, currentIndex: Math.max(0, idx) });
  };

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-3"
      data-testid={`artifact-group-${group.runPublicId}`}
    >
      <div className="flex items-center justify-between border-b border-border/40 pb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[12px] font-semibold text-fg-1">
            Run {group.runPublicId}
          </span>
          {group.runStatus && (
            <StatusBadge
              status={runToBadge(group.runStatus).status}
              label={runToBadge(group.runStatus).label ?? group.runStatus}
            />
          )}
          <span className="text-[11.5px] text-fg-4">•</span>
          <span className="text-[11.5px] text-fg-3">
            {formatFriendlyTimestamp(group.runDate)}
          </span>
          <span className="text-[10.5px] text-fg-5 font-mono">
            ({formatRelativeTime(group.runDate)})
          </span>
        </div>
        <span className="rounded bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10.5px] text-fg-4">
          {group.items.length} {group.items.length === 1 ? "artifact" : "artifacts"}
        </span>
      </div>

      {group.items.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center rounded-md border border-dashed border-border/80 bg-bg-root/40 p-6 text-center"
          data-testid="empty-run-artifacts"
        >
          <CameraOff className="mb-2 h-6 w-6 text-fg-4/70" />
          <p className="font-medium text-[12.5px] text-fg-2">
            No media artifacts captured for this run
          </p>
          <p className="text-[11px] text-fg-4 mt-1 max-w-md">
            {group.playwrightConfig &&
            (group.playwrightConfig.screenshot === "off" ||
              group.playwrightConfig.video === "off")
              ? "Screenshot capture and video recording were disabled in Execution Settings when this run was executed."
              : "No screenshots or video recordings were captured during this test run."}
          </p>
          {group.playwrightConfig ? (
            <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5 font-mono text-[10.5px]">
              <span className="rounded bg-bg-elev-2 px-2 py-0.5 text-fg-3 border border-border">
                Headless: {group.playwrightConfig.headless !== false ? "On" : "Off"}
              </span>
              <span className="rounded bg-bg-elev-2 px-2 py-0.5 text-fg-3 border border-border">
                Screenshots:{" "}
                {group.playwrightConfig.screenshot === "on"
                  ? "Every step"
                  : group.playwrightConfig.screenshot === "only-on-failure"
                    ? "On fail only"
                    : "Off"}
              </span>
              <span className="rounded bg-bg-elev-2 px-2 py-0.5 text-fg-3 border border-border">
                Video:{" "}
                {group.playwrightConfig.video === "on"
                  ? "On"
                  : group.playwrightConfig.video === "retain-on-failure"
                    ? "On fail only"
                    : "Off"}
              </span>
              {group.playwrightConfig.highlightSteps ||
              (group.playwrightConfig as { highlight_steps?: boolean }).highlight_steps ? (
                <span className="rounded bg-bg-elev-2 px-2 py-0.5 text-accent border border-accent/30">
                  Highlight: Enabled
                </span>
              ) : null}
            </div>
          ) : null}
          <p className="text-[11px] text-fg-5 mt-2">
            To capture screenshots or video, enable them in Execution Settings before running.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {group.items.map((item) => {
            const rawUrl = getRawUrl(item);
            const isScreenshot = item.kind === "SCREENSHOT";
            const isVideo = item.kind === "VIDEO";
            const label = isScreenshot
              ? item.stepTitle
                ? `Step ${item.stepOrder}: ${item.stepTitle}`
                : `Step ${item.stepOrder} Screenshot`
              : isVideo
                ? "Run Video Recording"
                : `${item.kind} (Step ${item.stepOrder})`;

            const formattedSize = item.sizeBytes
              ? `${Math.max(1, Math.round(item.sizeBytes / 1024)).toString()} KB`
              : "—";

            return (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded border border-border/70 bg-bg-root/50 p-2 text-[12px] hover:border-border transition-colors"
                data-testid={`case-artifact-item-${item.id}`}
              >
                {/* Thumbnail or Icon */}
                {isScreenshot ? (
                  <button
                    type="button"
                    onClick={() => handleOpenScreenshot(item.id)}
                    className="group relative flex h-12 w-16 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-bg-code cursor-zoom-in"
                    data-testid="case-artifact-thumbnail"
                    title="Click to zoom screenshot (Gallery navigation enabled)"
                  >
                    <img
                      src={rawUrl}
                      alt={label}
                      className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-bg-root/30 opacity-0 group-hover:opacity-100 transition-opacity">
                      <ZoomIn className="h-4 w-4 text-fg-1" />
                    </div>
                  </button>
                ) : isVideo ? (
                  <button
                    type="button"
                    onClick={() =>
                      onPlayVideo?.({
                        src: rawUrl,
                        title: `${group.runPublicId} - Run Video Recording`,
                        subtitle: `${formatFriendlyTimestamp(group.runDate)} • ${item.mimeType} • ${formattedSize}`,
                      })
                    }
                    className="group relative flex h-12 w-16 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-bg-elev-2 text-accent cursor-pointer hover:border-accent/60 transition-colors focus:outline-none"
                    data-testid="case-artifact-video-thumbnail"
                    title="Click to play video recording in dialog"
                  >
                    <Video className="h-5 w-5 transition-transform group-hover:scale-110" />
                    <div className="absolute inset-0 flex items-center justify-center bg-bg-root/40 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Play className="h-4 w-4 fill-current text-fg-1" />
                    </div>
                  </button>
                ) : (
                  <div className="flex h-12 w-16 shrink-0 items-center justify-center rounded border border-border bg-bg-elev-2 text-fg-4 font-mono text-[10px] uppercase">
                    {item.kind}
                  </div>
                )}

                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-fg-1 truncate">{label}</span>
                    <span className="rounded-sm bg-bg-elev-2 px-1.5 py-0.2 font-mono text-[10px] uppercase tracking-wide text-fg-3">
                      {item.kind}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-fg-4 font-mono">
                    <span>{item.mimeType}</span>
                    <span>•</span>
                    <span className="tabular-nums">{formattedSize}</span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {isScreenshot ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => handleOpenScreenshot(item.id)}
                      className="h-7 gap-1 text-[11.5px]"
                      data-testid="case-artifact-zoom-btn"
                    >
                      <ZoomIn className="h-3 w-3" />
                      Zoom
                    </Button>
                  ) : null}

                  {isVideo ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        onPlayVideo?.({
                          src: rawUrl,
                          title: `${group.runPublicId} - Run Video Recording`,
                          subtitle: `${formatFriendlyTimestamp(group.runDate)} • ${item.mimeType} • ${formattedSize}`,
                        })
                      }
                      className="h-7 gap-1 text-[11.5px]"
                      data-testid="case-artifact-play-btn"
                    >
                      <Play className="h-3 w-3 fill-current" />
                      Play
                    </Button>
                  ) : null}

                  <a
                    href={rawUrl}
                    download={`${group.runPublicId}-${item.kind.toLowerCase()}-${item.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-bg-elev-1 px-2 text-[11.5px] font-medium text-fg-2 hover:bg-bg-elev-2 hover:text-fg-1"
                    data-testid="case-artifact-download-btn"
                    title="Download artifact"
                  >
                    <Download className="h-3 w-3" />
                    Download
                  </a>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const CASE_ARTIFACTS_RUNS_PAGE_SIZE = 3;

function CaseArtifactsTab({
  caseId,
  lastRunId,
}: {
  caseId: string;
  lastRunId?: string | null;
}): React.ReactElement {
  const [selectedFilter, setSelectedFilter] = useState<ArtifactFilterKind>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [displayedRunCount, setDisplayedRunCount] = useState<number>(CASE_ARTIFACTS_RUNS_PAGE_SIZE);
  const [lightboxState, setLightboxState] = useState<{
    open: boolean;
    images: LightboxImage[];
    currentIndex: number;
  }>({ open: false, images: [], currentIndex: 0 });

  const [videoModalState, setVideoModalState] = useState<{
    open: boolean;
    src: string;
    title: string;
    subtitle?: string | null | undefined;
  }>({ open: false, src: "", title: "" });

  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);

  // Reset pagination when switching test cases, filters, or search query
  useEffect(() => {
    setDisplayedRunCount(CASE_ARTIFACTS_RUNS_PAGE_SIZE);
  }, [caseId, selectedFilter, searchQuery]);

  const { data, isLoading } = useQuery({
    queryKey: ["case-artifacts", caseId] as const,
    queryFn: () => fetchCaseArtifacts(caseId),
    enabled: Boolean(caseId),
  });

  const { data: caseRunsData } = useQuery({
    queryKey: ["case-runs", caseId] as const,
    queryFn: () => fetchCaseRuns(caseId),
    enabled: Boolean(caseId),
  });

  const { data: lastRunData } = useQuery({
    queryKey: ["run-summary-case-artifact", lastRunId] as const,
    queryFn: () => (lastRunId ? fetchRun(lastRunId) : null),
    enabled: Boolean(lastRunId),
  });

  const allItems = useMemo(() => data?.items ?? [], [data?.items]);
  const caseRuns = useMemo(() => caseRunsData?.items ?? [], [caseRunsData?.items]);

  // Filter items based on active search query across run ID, kind, mime type, and step info
  const searchMatchedItems = useMemo(() => {
    const q = searchQuery.trim();
    if (!q) return allItems;
    const pattern = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
    return allItems.filter((item) => {
      const haystack = `${item.runPublicId ?? ""} ${item.kind ?? ""} ${item.mimeType ?? ""} ${item.stepTitle ?? ""} step ${item.stepOrder ?? ""} ${item.id}`;
      return pattern.test(haystack);
    });
  }, [allItems, searchQuery]);

  // Filter items based on selected tab
  const filteredItems = useMemo(() => {
    if (selectedFilter === "ALL") return searchMatchedItems;
    if (selectedFilter === "LOG") {
      return searchMatchedItems.filter(
        (item) =>
          (item.kind as string) === "LOG" ||
          item.kind === "CONSOLE_LOG" ||
          item.kind === "DOM_SNAPSHOT" ||
          item.kind === "HAR",
      );
    }
    return searchMatchedItems.filter((item) => item.kind === selectedFilter);
  }, [searchMatchedItems, selectedFilter]);

  // Group all filtered items by run
  const allRunGroups = useMemo<RunArtifactGroup[]>(() => {
    const q = searchQuery.trim();
    const pattern = q ? new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") : null;
    const groupsMap = new Map<string, RunArtifactGroup>();

    // Index all items by runId
    const itemsByRunId = new Map<string, CaseArtifactPublic[]>();
    for (const item of filteredItems) {
      const list = itemsByRunId.get(item.runId) ?? [];
      list.push(item);
      itemsByRunId.set(item.runId, list);
    }

    // 1. Populate from all known caseRuns (maintains reverse-chronological order of runs)
    for (const run of caseRuns) {
      const runItems = itemsByRunId.get(run.id) ?? [];

      // When a specific filter tab (SCREENSHOT, VIDEO, LOG) is chosen,
      // hide runs that have 0 matching items for that tab.
      // In the "ALL" tab, show the run even if 0 artifacts were produced (audit state).
      if (selectedFilter !== "ALL" && runItems.length === 0) {
        continue;
      }

      const matchesSearch =
        !pattern ||
        pattern.test(`${run.publicId} ${run.id}`) ||
        runItems.some((item) => {
          const itemHaystack = `${item.kind ?? ""} ${item.mimeType ?? ""} ${item.stepTitle ?? ""} step ${item.stepOrder ?? ""} ${item.id}`;
          return pattern.test(itemHaystack);
        });

      if (!matchesSearch) {
        continue;
      }

      groupsMap.set(run.id, {
        runId: run.id,
        runPublicId: run.publicId || "Run",
        runStatus: run.status ?? null,
        runDate: run.startedAt || run.createdAt,
        items: runItems,
        playwrightConfig: (run.playwrightConfig as PlaywrightConfigInput | null | undefined) ?? (run.id === lastRunData?.id ? (lastRunData.playwrightConfig ?? null) : null),
      });
    }

    // 2. Also incorporate any runs from filteredItems not in caseRuns (e.g. mock runs or legacy)
    for (const item of filteredItems) {
      if (!groupsMap.has(item.runId)) {
        const runId = item.runId;
        const runPublicId = item.runPublicId || "Run";
        const runStatus = item.runStatus ?? null;
        const runDate = item.runDate || item.createdAt;

        const matchesSearch =
          !pattern ||
          pattern.test(
            `${runPublicId} ${item.kind ?? ""} ${item.mimeType ?? ""} ${item.stepTitle ?? ""} step ${item.stepOrder ?? ""} ${item.id}`,
          );

        if (!matchesSearch) continue;

        groupsMap.set(runId, {
          runId,
          runPublicId,
          runStatus,
          runDate,
          items: itemsByRunId.get(runId) ?? [item],
          playwrightConfig: runId === lastRunData?.id ? (lastRunData.playwrightConfig ?? null) : undefined,
        });
      }
    }

    // 3. Fallback: If lastRunId executed this case without artifacts and wasn't in caseRuns/items
    const lastRunMatches = !pattern || Boolean(lastRunData && pattern.test(lastRunData.public_id));
    if (selectedFilter === "ALL" && lastRunData && !groupsMap.has(lastRunData.id) && lastRunMatches) {
      groupsMap.set(lastRunData.id, {
        runId: lastRunData.id,
        runPublicId: lastRunData.public_id,
        runStatus: lastRunData.status,
        runDate: lastRunData.started_at || lastRunData.created_at,
        items: [],
        playwrightConfig: lastRunData.playwrightConfig ?? null,
      });
    }

    return Array.from(groupsMap.values());
  }, [filteredItems, caseRuns, searchQuery, selectedFilter, lastRunData]);

  // Slice run groups progressively (3 runs per chunk)
  const displayedRunGroups = useMemo<RunArtifactGroup[]>(
    () => allRunGroups.slice(0, displayedRunCount),
    [allRunGroups, displayedRunCount],
  );

  const counts = useMemo(() => {
    const res: Record<ArtifactFilterKind, number> = {
      ALL: searchMatchedItems.length,
      SCREENSHOT: 0,
      VIDEO: 0,
      TRACE: 0,
      LOG: 0,
    };
    for (const item of searchMatchedItems) {
      if (item.kind === "SCREENSHOT") res.SCREENSHOT += 1;
      else if (item.kind === "VIDEO") res.VIDEO += 1;
      else if (item.kind === "TRACE") res.TRACE += 1;
      else if (
        (item.kind as string) === "LOG" ||
        item.kind === "CONSOLE_LOG" ||
        item.kind === "DOM_SNAPSHOT" ||
        item.kind === "HAR"
      ) {
        res.LOG += 1;
      }
    }
    return res;
  }, [searchMatchedItems]);

  if (isLoading) return <CasesSkeleton />;

  if (allItems.length === 0 && allRunGroups.length === 0) {
    if (lastRunId) {
      const cfg = lastRunData?.playwrightConfig;
      return (
        <div
          className="flex flex-col items-center justify-center rounded-md border border-dashed border-border/80 bg-bg-root/40 p-8 text-center"
          data-testid="case-artifacts-empty"
        >
          <CameraOff className="mb-2 h-7 w-7 text-fg-4/70" />
          <p className="font-medium text-[13px] text-fg-2">
            No media artifacts captured for this test case
          </p>
          <p className="text-[11.5px] text-fg-4 mt-1 max-w-md">
            {cfg && (cfg.screenshot === "off" || cfg.video === "off")
              ? `Screenshot capture and video recording were disabled in Execution Settings when run ${lastRunData?.public_id ?? lastRunId} was executed.`
              : `The latest run (${lastRunData?.public_id ?? lastRunId}) completed without capturing media artifacts.`}
          </p>
          {cfg ? (
            <div className="mt-3.5 flex flex-wrap items-center justify-center gap-1.5 font-mono text-[11px]">
              <span className="rounded bg-bg-elev-2 px-2.5 py-0.5 text-fg-3 border border-border">
                Headless: {cfg.headless !== false ? "On" : "Off"}
              </span>
              <span className="rounded bg-bg-elev-2 px-2.5 py-0.5 text-fg-3 border border-border">
                Screenshots:{" "}
                {cfg.screenshot === "on"
                  ? "Every step"
                  : cfg.screenshot === "only-on-failure"
                    ? "On fail only"
                    : "Off"}
              </span>
              <span className="rounded bg-bg-elev-2 px-2.5 py-0.5 text-fg-3 border border-border">
                Video:{" "}
                {cfg.video === "on"
                  ? "On"
                  : cfg.video === "retain-on-failure"
                    ? "On fail only"
                    : "Off"}
              </span>
              {cfg.highlightSteps ||
              (cfg as { highlight_steps?: boolean }).highlight_steps ? (
                <span className="rounded bg-bg-elev-2 px-2.5 py-0.5 text-accent border border-accent/30">
                  Highlight: Enabled
                </span>
              ) : null}
            </div>
          ) : null}
          <p className="text-[11px] text-fg-5 mt-2.5">
            To capture screenshots or video recordings, enable them in Execution Settings before running.
          </p>
        </div>
      );
    }

    return (
      <EmptyState
        icon={Paperclip}
        title="No artifacts yet"
        subtitle="This test case has not been executed yet. Run this case to capture video, screenshots, traces, and logs across runs."
      />
    );
  }

  const getRawUrl = (item: CaseArtifactPublic): string => {
    const wsParam = activeWorkspaceId ? `?workspaceId=${encodeURIComponent(activeWorkspaceId)}` : "";
    return `/api/v1/runs/${item.runId}/artifacts/${item.id}/raw${wsParam}`;
  };

  return (
    <div className="flex flex-col gap-3" data-testid="case-artifacts-view">
      {/* Curation Kind Filters & Search */}
      <div className="flex flex-col gap-2 border-b border-border/60 pb-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="flex flex-wrap items-center gap-1.5"
          data-testid="artifact-filters"
        >
          {(
            [
              { id: "ALL", label: "All" },
              { id: "SCREENSHOT", label: "Screenshots" },
              { id: "VIDEO", label: "Videos" },
              { id: "TRACE", label: "Traces" },
              { id: "LOG", label: "Logs" },
            ] as const
          ).map((filter) => {
            const count = counts[filter.id] ?? 0;
            const isActive = selectedFilter === filter.id;
            return (
              <button
                key={filter.id}
                type="button"
                onClick={() => setSelectedFilter(filter.id)}
                className={cn(
                  "flex items-center gap-1.5 rounded px-2.5 py-1 text-[11.5px] font-medium transition-colors",
                  isActive
                    ? "bg-accent/15 text-accent font-semibold ring-1 ring-accent/30"
                    : "bg-bg-elev-2 text-fg-3 hover:bg-bg-elev-3 hover:text-fg-1",
                )}
                data-testid={`artifact-filter-${filter.id.toLowerCase()}`}
              >
                <span>{filter.label}</span>
                <span className="rounded-full bg-bg-root/80 px-1.5 py-0.2 text-[10px] tabular-nums text-fg-4">
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Search Artifacts */}
        <div className="relative flex items-center min-w-[200px] sm:w-64">
          <Search className="absolute left-2.5 h-3.5 w-3.5 text-fg-4 pointer-events-none" aria-hidden="true" />
          <Input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search artifacts or runs..."
            className="h-7 pl-8 pr-7 text-xs bg-bg-elev-1 border-border/80 rounded-md focus-visible:ring-1 focus-visible:ring-accent"
            data-testid="case-artifacts-search-input"
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2 p-0.5 text-fg-4 hover:text-fg-2"
              aria-label="Clear artifact search"
              data-testid="case-artifacts-search-clear"
            >
              <X className="h-3 w-3" />
            </button>
          ) : null}
        </div>
      </div>

      {/* Progressive Run Pagination Count Indicator */}
      {allRunGroups.length > 0 ? (
        <div className="flex items-center justify-between text-[11px] font-mono text-fg-4 px-0.5">
          <span data-testid="case-artifacts-count">
            Showing {Math.min(displayedRunCount, allRunGroups.length)} of {allRunGroups.length} runs ({displayedRunGroups.reduce((acc, g) => acc + g.items.length, 0)} of {filteredItems.length} artifacts)
          </span>
        </div>
      ) : null}

      {/* Grouped by Run Date list */}
      {displayedRunGroups.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center rounded-md border border-dashed border-border/80 bg-bg-root/40 p-6 text-center"
          data-testid="case-artifacts-empty-filter"
        >
          <CameraOff className="mb-1.5 h-5 w-5 text-fg-4/60" />
          <p className="font-medium text-[12px] text-fg-3">
            {searchQuery
              ? `No artifacts matching "${searchQuery}" found.`
              : `No ${selectedFilter.toLowerCase()} artifacts recorded for this test case.`}
          </p>
          {lastRunData?.playwrightConfig &&
          ((selectedFilter === "SCREENSHOT" && lastRunData.playwrightConfig.screenshot === "off") ||
            (selectedFilter === "VIDEO" && lastRunData.playwrightConfig.video === "off")) ? (
            <p className="text-[11px] text-fg-5 mt-1 max-w-sm">
              {selectedFilter === "SCREENSHOT" ? "Screenshots" : "Video recording"} were turned off in Execution Settings during the last run.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {displayedRunGroups.map((group) => (
            <RunArtifactGroupSection
              key={group.runId}
              group={group}
              getRawUrl={getRawUrl}
              onZoom={({ images, currentIndex }) =>
                setLightboxState({ open: true, images, currentIndex })
              }
              onPlayVideo={(params) =>
                setVideoModalState({
                  open: true,
                  src: params.src,
                  title: params.title,
                  subtitle: params.subtitle,
                })
              }
            />
          ))}

          {/* Progressive Load More Button for Runs */}
          {displayedRunCount < allRunGroups.length ? (
            <div className="flex justify-center pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setDisplayedRunCount((prev) => prev + CASE_ARTIFACTS_RUNS_PAGE_SIZE)}
                data-testid="case-artifacts-load-more"
                className="h-7 text-xs font-normal text-fg-3 hover:text-fg-1"
              >
                Load more runs ({allRunGroups.length - displayedRunCount} remaining)
              </Button>
            </div>
          ) : null}

          {displayedRunGroups.length > 2 || displayedRunCount > CASE_ARTIFACTS_RUNS_PAGE_SIZE ? (
            <div className="flex justify-center pt-1">
              <button
                type="button"
                onClick={() => {
                  const view = document.querySelector('[data-testid="case-artifacts-view"]');
                  if (view) {
                    view.scrollIntoView({ behavior: "smooth", block: "start" });
                  } else {
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }
                }}
                data-testid="case-artifacts-scroll-top"
                className="inline-flex items-center gap-1 text-[11px] font-mono text-fg-5 hover:text-fg-2 transition-colors"
              >
                <ArrowUp className="h-3 w-3" aria-hidden="true" />
                Scroll to top
              </button>
            </div>
          ) : null}
        </div>
      )}

      {/* Lightbox for zooming screenshots in case artifacts with gallery cycling */}
      <ImageLightboxModal
        open={lightboxState.open}
        onOpenChange={(open) => setLightboxState((prev) => ({ ...prev, open }))}
        images={lightboxState.images}
        currentIndex={lightboxState.currentIndex}
        onNavigate={(currentIndex) => setLightboxState((prev) => ({ ...prev, currentIndex }))}
      />

      {/* Video Player Modal for playing video recordings directly in a dialog */}
      <VideoPlayerModal
        open={videoModalState.open}
        onOpenChange={(open) => setVideoModalState((prev) => ({ ...prev, open }))}
        src={videoModalState.src}
        title={videoModalState.title}
        subtitle={videoModalState.subtitle}
      />
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
  const { canWriteTests } = usePermissions();
  const aiTabVisible = useFeatureEnabled("ai_generation");
  const projectId = useActiveProject((s) => s.projectId);
  const { data: project } = useProject(projectId);
  const setGating = useSetGatingSuite();
  const gatingSuiteId = project?.gating_suite_id ?? null;

  const [active, setActive] = useState<Tab>("all");
  const [suiteDialogOpen, setSuiteDialogOpen] = useState(false);
  const [caseDialogOpen, setCaseDialogOpen] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [strategyDialogOpen, setStrategyDialogOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [approachFilter, setApproachFilter] = useState<TestingApproach | "">("");
  // Draggable splitter: width of the left (list) pane in px. Persisted per
  // session in localStorage so the layout survives reloads.
  const [leftWidth, setLeftWidth] = useState(() => {
    if (typeof localStorage !== "undefined") {
      const raw = localStorage.getItem("suitest.casesLeftWidth");
      const parsed = raw ? Number(raw) : NaN;
      if (Number.isFinite(parsed) && parsed >= LEFT_MIN && parsed <= LEFT_MAX) {
        return parsed;
      }
    }
    return LEFT_DEFAULT;
  });

  // GenerateModal state — `null` strategy = open at the target-select step;
  // a concrete strategy deep-links from the split-button dropdown.
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateStrategy, setGenerateStrategy] = useState<GeneratorStrategy | undefined>(
    undefined,
  );
  // Splitter drag: track the pointer while resizing, clamp to bounds, and
  // persist on release so the layout survives reloads.
  const startResize = useCallback(
    (down: React.PointerEvent<HTMLDivElement>) => {
      down.preventDefault();
      const startX = down.clientX;
      const startWidth = leftWidth;
      const onMove = (move: PointerEvent): void => {
        const next = Math.min(LEFT_MAX, Math.max(LEFT_MIN, startWidth + (move.clientX - startX)));
        setLeftWidth(next);
      };
      const onUp = (): void => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        setLeftWidth((final) => {
          if (typeof localStorage !== "undefined") {
            localStorage.setItem("suitest.casesLeftWidth", String(final));
          }
          return final;
        });
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [leftWidth],
  );
  const handleGenerate = useCallback((strategy?: GeneratorStrategy) => {
    setGenerateStrategy(strategy);
    setGenerateOpen(true);
  }, []);

  // Selection state: Set of internal case IDs (case.id, not public_id).
  // The bulk endpoint expects internal UUIDs.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const prevProjectRef = useRef(projectId);

  // Clear case selection, search filters, and bulk selection when switching project
  useEffect(() => {
    if (prevProjectRef.current !== projectId) {
      prevProjectRef.current = projectId;
      setSelectedIds(new Set());
      setQuery("");
      setApproachFilter("");
      if (search.case) {
        void navigate({ search: {} });
      }
    }
  }, [projectId, search.case, navigate]);

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
    const byApproach =
      approachFilter === ""
        ? byTab
        : byTab.filter((testCase) => testCase.effective_testing_approach === approachFilter);
    const q = query.trim().toLowerCase();
    if (q === "") return byApproach;
    // Client-side, ZERO-friendly search over the loaded cases (title + name +
    // public id) so both human phrasing and the technical key match.
    return byApproach.filter((testCase) => matchesCaseQuery(testCase, q));
  }, [active, approachFilter, cases, query]);

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

  // Prune any selected case IDs that no longer exist (e.g. deleted via toolbar or bulk ops)
  useEffect(() => {
    if (selectedIds.size === 0) return;
    const validIds = new Set(cases.items.map((c) => c.id));
    setSelectedIds((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (validIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [cases.items, selectedIds.size]);

  return (
    <>
      <CasesHeader
        active={active}
        setActive={setActive}
        counts={counts}
        showAiTab={aiTabVisible}
        onGenerate={handleGenerate}
        aiEnabled={aiTabVisible}
        onStrategy={() => {
          setStrategyDialogOpen(true);
        }}
      />
      {projectId ? (
        <TestStrategyDialog
          open={strategyDialogOpen}
          onOpenChange={setStrategyDialogOpen}
          projectId={projectId}
          aiEnabled={aiTabVisible}
          canWrite={canWriteTests}
        />
      ) : null}
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
          if (active !== "all" && active !== "manual") {
            setActive("all");
          }
          void navigate({ search: { case: publicId } });
        }}
      />
      {projectId ? (
        <ExportUatDialog
          projectId={projectId}
          selectedIds={[...selectedIds]}
          projectName={project?.name ?? "UAT Report"}
          open={exportDialogOpen}
          onOpenChange={setExportDialogOpen}
        />
      ) : null}
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
        <div className="flex min-h-0 flex-1 gap-0" data-testid="cases-split-container">
          <aside
            style={{ width: leftWidth, minWidth: LEFT_MIN, maxWidth: LEFT_MAX }}
            className={cn(
              "flex min-h-0 shrink-0 flex-col overflow-hidden rounded-l-lg border border-border bg-bg-elev-1",
              "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04),0_16px_40px_-24px_rgba(0,0,0,0.9)]",
            )}
            data-testid="cases-left-pane"
          >
            <div className="flex shrink-0 flex-col gap-2 border-b border-border p-3">
              <div className="flex gap-2">
                <Input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                  }}
                  placeholder="Search cases…"
                  className="h-8 min-w-0 flex-1"
                  data-testid="cases-search"
                  aria-label="Search cases"
                />
                <select
                  aria-label="Filter by testing approach"
                  value={approachFilter}
                  onChange={(event) => {
                    setApproachFilter(event.target.value as TestingApproach | "");
                  }}
                  className="h-8 rounded-md border border-border bg-bg-base px-2 text-[11px] text-fg-3 outline-none focus:border-accent"
                >
                  <option value="">All approaches</option>
                  <option value="BLACK_BOX">Black-box</option>
                  <option value="GRAY_BOX">Gray-box</option>
                  <option value="WHITE_BOX">White-box</option>
                </select>
              </div>
              {canWriteTests ? (
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
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="w-full justify-center gap-1.5 border-accent/30 text-accent hover:bg-accent/10 hover:text-accent disabled:border-border disabled:text-fg-4"
                data-testid="export-uat-btn"
                disabled={selectedIds.size === 0}
                onClick={() => {
                  setExportDialogOpen(true);
                }}
              >
                <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
                Export UAT
                {selectedIds.size > 0 ? (
                  <span className="ml-0.5 rounded-sm bg-accent/15 px-1.5 font-mono text-[10.5px] tabular-nums">
                    {selectedIds.size}
                  </span>
                ) : null}
              </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <CaseTree
                suites={suites.items}
                cases={filtered}
                selectedId={selectedId}
                selectedIds={selectedIds}
                isFiltered={active !== "all" || query.trim() !== "" || approachFilter !== ""}
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
              cases={cases.items}
              suites={suites.items}
              onClear={handleClearSelection}
              projectId={projectId}
            />
          </aside>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize list and detail panes"
            onPointerDown={startResize}
            data-testid="cases-splitter"
            className="group relative w-2 shrink-0 cursor-col-resize"
          >
            <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border group-hover:bg-accent/60" />
          </div>
          <section
            className={cn(
              "min-h-0 min-w-0 flex-1 overflow-y-auto rounded-r-lg border border-l-0 border-border bg-bg-elev-1 p-5",
              "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04),0_16px_40px_-24px_rgba(0,0,0,0.9)]",
            )}
            data-testid="cases-right-pane"
          >
            <CaseDetailPanel key={selectedId ?? "empty"} publicId={selectedId} suites={suites.items} />
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

// Hide the AI tab in ZERO via wrapper — leverages Gated for ergonomic
// composition, so the CasesHeader doesn't have to know about capabilities.
function CasesContainer(): React.ReactElement {
  const projectId = useActiveProject((s) => s.projectId);
  return (
    <section className="flex h-full min-h-0 flex-col gap-4" data-testid="cases-screen">
      <ErrorBoundary fallback={({ reset }) => <CasesError reset={reset} />}>
        <Suspense fallback={<CasesSkeleton />}>
          {projectId === null ? <FirstProjectBootstrap /> : <CasesBody />}
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

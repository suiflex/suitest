/**
 * StepEditor — M1-12 inline step editor for test case detail panel.
 * M1-14 — drag-reorder via dnd-kit.
 *
 * Props:
 *   caseId       — the public_id of the test case (e.g. "TC-101")
 *   steps        — current draft steps (caller owns state)
 *   onStepsChange — called whenever local draft changes; caller should
 *                   update its own state so the list re-renders
 *
 * API contracts used:
 *   POST  /test-cases/:id/steps                — body: StepAppend (camelCase aliases)
 *   PATCH /test-cases/:id/steps                — body: StepReplace { steps: [...] }
 *   PATCH /test-cases/:id/steps/reorder        — body: { stepIdsInOrder: string[] }
 *
 * Editing remains available without an LLM; execution is gated separately.
 */

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Code, GripVertical, Plus, Trash2, Wrench } from "lucide-react";
import { useCallback, useState } from "react";

import { SelectorRepairDialog } from "@/components/cases/SelectorRepairDialog";
import { Gated } from "@/components/gating/Gated";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { api, ApiError } from "@/lib/api-client";
import { outcomeToBadge } from "@/lib/badge-maps";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

export interface StepEditorError {
  message: string;
  title?: string | undefined;
  stepIndex?: number | undefined;
  code?: string | undefined;
}

type TargetKind = components["schemas"]["TargetKind"];
type TestCaseDetail = components["schemas"]["TestCaseDetail"];
type StepOutcome = components["schemas"]["StepOutcome"];

/**
 * DraftStep mirrors TestStepPublic but `id` may be a temporary client-side
 * string while the step hasn't been persisted yet (prefix "__new__").
 */
export interface DraftStep {
  id: string;
  order: number;
  action: string;
  expected: string;
  code: string | null;
  mcp_provider: string;
  target_kind: TargetKind;
}

/**
 * Convert DraftStep[] to the StepCreate payload shape accepted by the BE.
 * The BE uses camelCase aliases for mcp_provider and target_kind.
 */
function toBulkPayload(steps: DraftStep[]): {
  steps: {
    action: string;
    expected: string;
    code: string | null;
    mcpProvider: string;
    targetKind: TargetKind;
    order: number;
  }[];
} {
  return {
    steps: steps.map((s, idx) => ({
      action: s.action,
      expected: s.expected,
      code: s.code ?? null,
      mcpProvider: s.mcp_provider,
      targetKind: s.target_kind,
      order: idx + 1,
    })),
  };
}

function removeAndReorder(steps: DraftStep[], stepId: string): DraftStep[] {
  const remaining = steps.filter((step) => step.id !== stepId);
  return remaining.map((step, index) => ({ ...step, order: index + 1 }));
}

const TARGET_KINDS: TargetKind[] = [
  "FE_WEB",
  "FE_MOBILE",
  "BE_REST",
  "BE_GRAPHQL",
  "BE_GRPC",
  "DATA",
  "INFRA",
  "CUSTOM",
];

/** Returns true when a step id is a real server-persisted id (not a draft). */
function isPersisted(id: string): boolean {
  return !id.startsWith("__new__");
}

// ---------------------------------------------------------------------------
// StepEditor component
// ---------------------------------------------------------------------------
interface StepEditorProps {
  caseId: string;
  /** Current steps (drafts allowed — ids prefixed "__new__"). */
  steps: DraftStep[];
  onStepsChange: (steps: DraftStep[]) => void;
  /** Last-run outcome per step order — pass-through for the pass/fail badge. */
  outcomeByOrder?: Map<number, StepOutcome>;
}
export function StepEditor({
  caseId,
  steps,
  onStepsChange,
  outcomeByOrder,
}: StepEditorProps): React.ReactElement {
  const queryClient = useQueryClient();
  const [error, setError] = useState<StepEditorError | null>(null);
  const [repairStep, setRepairStep] = useState<DraftStep | null>(null);

  // ------------------------------------------------------------------
  // PATCH /test-cases/:id/steps — bulk replace (save edits / remove)
  // ------------------------------------------------------------------
  const replaceStepsMutation = useMutation({
    mutationFn: async (nextSteps: DraftStep[]) => {
      const res = await api.patch<TestCaseDetail>(
        `/test-cases/${caseId}/steps`,
        toBulkPayload(nextSteps),
      );
      return res.data;
    },
    onSuccess: (detail) => {
      const serverSteps: DraftStep[] = (detail.steps ?? []).map((s) => ({
        id: s.id,
        order: s.order,
        action: s.action,
        expected: s.expected,
        code: s.code ?? null,
        mcp_provider: s.mcp_provider,
        target_kind: s.target_kind,
      }));
      onStepsChange(serverSteps);
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
      setError(null);
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError) {
        const stepIndex =
          typeof err.details?.stepIndex === "number"
            ? (err.details.stepIndex as number)
            : undefined;
        const stepOrder =
          typeof err.details?.stepOrder === "number"
            ? (err.details.stepOrder as number)
            : stepIndex !== undefined
              ? stepIndex + 1
              : undefined;

        if (err.code === "MCP_PROVIDER_NOT_REGISTERED") {
          const name = typeof err.details?.name === "string" ? err.details.name : "";
          setError({
            code: err.code,
            title: "Unregistered MCP Provider",
            message: `Step #${stepOrder ?? (stepIndex !== undefined ? stepIndex + 1 : 1)} references MCP provider '${name}', which is not registered in this workspace.`,
            stepIndex,
          });
          return;
        }

        setError({
          code: err.code,
          title: "Failed to save steps",
          message: err.message,
          stepIndex,
        });
        return;
      }

      const msg = err instanceof Error ? err.message : "Failed to save steps";
      setError({
        title: "Failed to save steps",
        message: msg,
      });
    },
  });

  // ------------------------------------------------------------------
  // PATCH /test-cases/:id/steps/reorder — M1-14 drag reorder
  // ------------------------------------------------------------------
  const reorderMutation = useMutation({
    mutationFn: async (stepIdsInOrder: string[]) => {
      const res = await api.patch<TestCaseDetail>(`/test-cases/${caseId}/steps/reorder`, {
        stepIdsInOrder,
      });
      return res.data;
    },
    onSuccess: (detail) => {
      const serverSteps: DraftStep[] = (detail.steps ?? []).map((s) => ({
        id: s.id,
        order: s.order,
        action: s.action,
        expected: s.expected,
        code: s.code ?? null,
        mcp_provider: s.mcp_provider,
        target_kind: s.target_kind,
      }));
      onStepsChange(serverSteps);
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
      setError(null);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to reorder steps";
      setError({
        title: "Failed to reorder steps",
        message: msg,
      });
    },
  });

  // ------------------------------------------------------------------
  // Local field update — no network call; caller re-renders
  // ------------------------------------------------------------------
  const handleFieldChange = useCallback(
    (stepId: string, field: keyof DraftStep, value: string) => {
      setError((prev) => {
        if (!prev || prev.stepIndex === undefined) return prev;
        const targetStep = steps[prev.stepIndex];
        if (targetStep && targetStep.id === stepId) {
          return null;
        }
        return prev;
      });
      const updated = steps.map((s) =>
        s.id === stepId
          ? {
              ...s,
              [field]: field === "target_kind" ? (value as TargetKind) : value,
            }
          : s,
      );
      onStepsChange(updated);
    },
    [steps, onStepsChange],
  );

  // ------------------------------------------------------------------
  // Remove a step — local update + conditional server sync
  // ------------------------------------------------------------------
  const handleRemove = useCallback(
    (stepId: string) => {
      const remaining = removeAndReorder(steps, stepId);
      // Optimistic update
      onStepsChange(remaining);

      // Adjust or clear any active error pointing to the removed step or beyond
      setError((prev) => {
        if (!prev || prev.stepIndex === undefined) return null;
        const removedIndex = steps.findIndex((s) => s.id === stepId);
        if (removedIndex === prev.stepIndex) return null;
        if (removedIndex < prev.stepIndex) {
          return {
            ...prev,
            stepIndex: prev.stepIndex - 1,
          };
        }
        return prev;
      });

      // Draft steps exist only on the client — no server mutation needed
      if (!isPersisted(stepId)) return;

      // If any remaining steps are unpersisted drafts, defer sync to "Save steps"
      if (remaining.some((s) => !isPersisted(s.id))) return;

      replaceStepsMutation.mutate(remaining);
    },
    [steps, onStepsChange, replaceStepsMutation],
  );

  // ------------------------------------------------------------------
  // Save — commit current draft via PATCH
  // ------------------------------------------------------------------
  const handleSave = useCallback(() => {
    setError(null);
    replaceStepsMutation.mutate(steps);
  }, [steps, replaceStepsMutation]);

  // ------------------------------------------------------------------
  // dnd-kit drag sensors
  // ------------------------------------------------------------------
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // ------------------------------------------------------------------
  // Drag end handler — M1-14; drafts participate too. Server-side reorder
  // only re-orders persisted rows: when a draft is involved, ordering lands
  // on the server with the next Save steps (bulk replace).
  // ------------------------------------------------------------------
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const activeId = String(active.id);
      const overId = String(over.id);

      const oldIndex = steps.findIndex((s) => s.id === activeId);
      const newIndex = steps.findIndex((s) => s.id === overId);
      if (oldIndex === -1 || newIndex === -1) return;

      const reordered = arrayMove(steps, oldIndex, newIndex).map((s, idx) => ({
        ...s,
        order: idx + 1,
      }));

      // Optimistic local update
      onStepsChange(reordered);

      const allPersisted = reordered.every((s) => isPersisted(s.id));
      if (!allPersisted) return;

      reorderMutation.mutate(reordered.map((s) => s.id));
    },
    [steps, onStepsChange, reorderMutation],
  );

  const saving =
    replaceStepsMutation.isPending || reorderMutation.isPending;

  const sortableIds = steps.map((s) => s.id);

  return (
    <section className="flex flex-col gap-2" data-testid="step-editor">
      <div className="flex items-center justify-between">
        <h4 className="text-[13px] font-semibold text-fg-1">Steps</h4>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="step-save-btn"
            disabled={saving}
            onClick={handleSave}
          >
            {replaceStepsMutation.isPending ? "Saving…" : "Save steps"}
          </Button>
          <Button
            type="button"
            size="sm"
            data-testid="step-add-btn"
            onClick={() => {
              // Client-side draft: no API call until "Save steps". The
              // "__new__" id prefix marks it as unpersisted (drag-disabled,
              // replaced wholesale by the PATCH on save).
              const draft: DraftStep = {
                id: `__new__${crypto.randomUUID()}`,
                order: steps.length + 1,
                action: "",
                expected: "",
                code: null,
                mcp_provider: "playwright-mcp",
                target_kind: "FE_WEB",
              };
              onStepsChange([...steps, draft]);
            }}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New step
          </Button>
        </div>
      </div>

      {error ? (
        <div
          data-testid="step-editor-error"
          className="flex items-start gap-2.5 rounded-md border border-red/40 bg-red/10 p-3 text-[12px] text-red"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red" aria-hidden="true" />
          <div className="flex flex-1 flex-col gap-0.5">
            {error.title ? (
              <span className="font-semibold text-fg-1">{error.title}</span>
            ) : null}
            <span className="leading-relaxed text-fg-2">{error.message}</span>
          </div>
        </div>
      ) : null}

      {steps.length === 0 ? (
        <div className="rounded-md border border-border bg-bg-elev-2 px-4 py-6 text-center text-[12px] text-fg-4">
          No steps yet. Click &quot;+ New step&quot; to add one.
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
            <ol className="flex flex-col gap-2">
              {steps.map((step, idx) => (
                <StepRow
                  key={step.id}
                  step={step}
                  index={idx}
                  disabled={saving}
                  hasError={error?.stepIndex === idx}
                  outcome={outcomeByOrder?.get(idx + 1)}
                  onFieldChange={handleFieldChange}
                  onRemove={handleRemove}
                  onRepair={() => {
                    setRepairStep(step);
                  }}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}
      {repairStep ? (
        <SelectorRepairDialog
          open
          onOpenChange={(open) => {
            if (!open) setRepairStep(null);
          }}
          caseId={caseId}
          stepId={repairStep.id}
          onApplied={(code) => {
            onStepsChange(
              steps.map((step) => (step.id === repairStep.id ? { ...step, code } : step)),
            );
            void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
          }}
        />
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// StepRow — a single editable step, with optional sortable drag handle
// ---------------------------------------------------------------------------

interface StepRowProps {
  step: DraftStep;
  index: number;
  disabled: boolean;
  hasError?: boolean | undefined;
  outcome?: StepOutcome | undefined;
  onFieldChange: (stepId: string, field: keyof DraftStep, value: string) => void;
  onRemove: (stepId: string) => void;
  onRepair: () => void;
}

function StepRow({
  step,
  index,
  disabled,
  hasError,
  outcome,
  onFieldChange,
  onRemove,
  onRepair,
}: StepRowProps): React.ReactElement {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: step.id,
    disabled,
  });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : undefined,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      data-testid="step-row"
      className={cn(
        "rounded-md border p-3 transition-colors",
        hasError
          ? "border-red/60 bg-red/[0.04] ring-1 ring-red/30"
          : "border-border bg-bg-elev-1",
      )}
    >
      {/* Header row: drag handle + order badge + action input + outcome + remove */}
      <div className="mb-2 flex items-center gap-2">
        <button
          type="button"
          data-testid="step-drag-handle"
          className={cn(
            "shrink-0 cursor-grab text-fg-4 hover:text-fg-3 active:cursor-grabbing",
            disabled && "pointer-events-none opacity-50",
          )}
          aria-label="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-bg-elev-2 font-mono text-[10.5px] text-fg-4">
          {index + 1}
        </span>
        {!isPersisted(step.id) ? (
          <span
            className="shrink-0 rounded-full border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wide text-accent"
            data-testid="step-draft-badge"
          >
            new
          </span>
        ) : null}
        {outcome ? (
          <StatusBadge status={outcomeToBadge(outcome)} label={outcome} />
        ) : null}
        <Input
          data-testid="step-action-input"
          className={cn(
            "h-7 flex-1 border-border bg-bg-elev-2 font-sans text-[12.5px] text-fg-1 placeholder:text-fg-5",
            "focus-visible:border-accent/60 focus-visible:ring-accent/20",
          )}
          placeholder="Action description"
          value={step.action}
          disabled={disabled}
          onChange={(e) => {
            onFieldChange(step.id, "action", e.target.value);
          }}
        />
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          data-testid="step-remove-btn"
          disabled={disabled}
          className="shrink-0 text-fg-4 hover:text-red"
          onClick={() => {
            onRemove(step.id);
          }}
          aria-label="Remove step"
        >
          <Trash2 className="h-3 w-3" aria-hidden="true" />
        </Button>
        {step.target_kind === "FE_WEB" && step.code ? (
          <Gated feature="autonomy_assist">
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              disabled={disabled}
              className="shrink-0 text-violet hover:text-fg-1"
              onClick={onRepair}
              aria-label="Repair changed selector"
            >
              <Wrench className="h-3 w-3" aria-hidden="true" />
            </Button>
          </Gated>
        ) : null}
      </div>

      {/* Expected (read-only label for now — mutable in M1-13) */}
      <div className="mb-2 flex items-center gap-2">
        <span className="w-[52px] shrink-0 text-[10.5px] text-fg-5">Expected</span>
        <Input
          data-testid="step-expected-input"
          className={cn(
            "h-7 flex-1 border-border bg-bg-elev-2 font-sans text-[12px] text-fg-3 placeholder:text-fg-5",
            "focus-visible:border-accent/60 focus-visible:ring-accent/20",
          )}
          placeholder="Expected result"
          value={step.expected}
          disabled={disabled}
          onChange={(e) => {
            onFieldChange(step.id, "expected", e.target.value);
          }}
        />
      </div>

      {/* Provider + target kind row */}
      <div className="mb-2 flex items-center gap-2">
        <span className="w-[52px] shrink-0 text-[10.5px] text-fg-5">Provider</span>
        <Input
          data-testid="step-provider-input"
          className={cn(
            "h-7 flex-1 border-border bg-bg-elev-2 font-mono text-[11px] text-fg-3 placeholder:text-fg-5",
            "focus-visible:border-accent/60 focus-visible:ring-accent/20",
          )}
          placeholder="playwright-mcp"
          value={step.mcp_provider}
          disabled={disabled}
          onChange={(e) => {
            onFieldChange(step.id, "mcp_provider", e.target.value);
          }}
        />
        <select
          data-testid="step-target-kind-select"
          value={step.target_kind}
          disabled={disabled}
          onChange={(e) => {
            onFieldChange(step.id, "target_kind", e.target.value);
          }}
          className={cn(
            "h-7 rounded-md border border-border bg-bg-elev-2 px-2 font-mono text-[11px] text-fg-3",
            "focus:outline-none focus:ring-1 focus:ring-accent/40",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {TARGET_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>

      {/* Code textarea */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-start gap-2">
          <Code
            className={cn(
              "mt-1.5 h-3 w-3 shrink-0",
              hasError ? "text-red" : "text-fg-5",
            )}
            aria-hidden="true"
          />
          <div className="flex flex-1 flex-col gap-1">
            <textarea
              data-testid="step-code-input"
              className={cn(
                "w-full resize-y rounded-md border p-2",
                "font-mono text-[11px]",
                "focus:outline-none focus:ring-1",
                "disabled:cursor-not-allowed disabled:opacity-50",
                "min-h-[56px]",
                hasError
                  ? "border-red/70 bg-red/[0.06] text-fg-1 placeholder:text-red/60 focus:ring-red/50"
                  : "border-border bg-bg-code text-fg-3 placeholder:text-fg-5 focus:ring-accent/40",
              )}
              placeholder="// Optional: MCP step code"
              value={step.code ?? ""}
              disabled={disabled}
              onChange={(e) => {
                onFieldChange(step.id, "code", e.target.value);
              }}
            />
          </div>
        </div>
      </div>
    </li>
  );
}

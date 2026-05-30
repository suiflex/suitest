/**
 * StepEditor — M1-12 inline step editor for test case detail panel.
 *
 * Props:
 *   caseId       — the public_id of the test case (e.g. "TC-101")
 *   steps        — current draft steps (caller owns state)
 *   onStepsChange — called whenever local draft changes; caller should
 *                   update its own state so the list re-renders
 *
 * API contracts used:
 *   POST  /test-cases/:id/steps         — body: StepAppend (camelCase aliases)
 *   PATCH /test-cases/:id/steps         — body: StepReplace { steps: [...] }
 *
 * ZERO-tier compatible: no LLM calls, no capability gating needed.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Code, Plus, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TargetKind = components["schemas"]["TargetKind"];
type TestCaseDetail = components["schemas"]["TestCaseDetail"];

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

// ---------------------------------------------------------------------------
// StepEditor component
// ---------------------------------------------------------------------------

interface StepEditorProps {
  caseId: string;
  steps: DraftStep[];
  onStepsChange: (steps: DraftStep[]) => void;
}

export function StepEditor({ caseId, steps, onStepsChange }: StepEditorProps): React.ReactElement {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // ------------------------------------------------------------------
  // POST /test-cases/:id/steps — append a blank step
  // ------------------------------------------------------------------
  const addStepMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        action: "",
        expected: "",
        code: null,
        mcpProvider: "playwright-mcp",
        targetKind: "FE_WEB" as TargetKind,
      };
      const res = await api.post<TestCaseDetail>(`/test-cases/${caseId}/steps`, payload);
      return res.data;
    },
    onSuccess: (detail) => {
      const newSteps: DraftStep[] = (detail.steps ?? []).map((s) => ({
        id: s.id,
        order: s.order,
        action: s.action,
        expected: s.expected,
        code: s.code ?? null,
        mcp_provider: s.mcp_provider,
        target_kind: s.target_kind,
      }));
      onStepsChange(newSteps);
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
      setError(null);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to add step";
      setError(msg);
    },
  });

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
      const msg = err instanceof Error ? err.message : "Failed to save steps";
      setError(msg);
    },
  });

  // ------------------------------------------------------------------
  // Local field update — no network call; caller re-renders
  // ------------------------------------------------------------------
  const handleFieldChange = useCallback(
    (stepId: string, field: keyof DraftStep, value: string) => {
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
  // Remove a step — optimistic: update local state, then PATCH
  // ------------------------------------------------------------------
  const handleRemove = useCallback(
    (stepId: string) => {
      const snapshot = steps;
      const remaining = steps
        .filter((s) => s.id !== stepId)
        .map((s, idx) => ({ ...s, order: idx + 1 }));
      // Optimistic update
      onStepsChange(remaining);
      replaceStepsMutation.mutate(remaining, {
        onError: () => {
          // Rollback on failure
          onStepsChange(snapshot);
        },
      });
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

  const saving = replaceStepsMutation.isPending || addStepMutation.isPending;

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
            disabled={saving}
            onClick={() => {
              addStepMutation.mutate();
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
          className="rounded-md border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red"
        >
          {error}
        </div>
      ) : null}

      {steps.length === 0 ? (
        <div className="rounded-md border border-dashed border-border px-4 py-6 text-center text-[12px] text-fg-4">
          No steps yet. Click &quot;+ New step&quot; to add one.
        </div>
      ) : (
        <ol className="flex flex-col gap-2">
          {steps.map((step, idx) => (
            <StepRow
              key={step.id}
              step={step}
              index={idx}
              disabled={saving}
              onFieldChange={handleFieldChange}
              onRemove={handleRemove}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// StepRow — a single editable step
// ---------------------------------------------------------------------------

interface StepRowProps {
  step: DraftStep;
  index: number;
  disabled: boolean;
  onFieldChange: (stepId: string, field: keyof DraftStep, value: string) => void;
  onRemove: (stepId: string) => void;
}

function StepRow({ step, index, disabled, onFieldChange, onRemove }: StepRowProps): React.ReactElement {
  return (
    <li
      data-testid="step-row"
      className="rounded-md border border-border bg-bg-elev-1 p-3"
    >
      {/* Header row: order badge + action input + remove button */}
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-bg-elev-2 font-mono text-[10.5px] text-fg-4">
          {index + 1}
        </span>
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
      <div className="flex items-start gap-2">
        <Code className="mt-1.5 h-3 w-3 shrink-0 text-fg-5" aria-hidden="true" />
        <textarea
          data-testid="step-code-input"
          className={cn(
            "w-full resize-y rounded-md border border-border bg-[#060606] p-2",
            "font-mono text-[11px] text-fg-3 placeholder:text-fg-5",
            "focus:outline-none focus:ring-1 focus:ring-accent/40",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "min-h-[56px]",
          )}
          placeholder="// Optional: MCP step code"
          value={step.code ?? ""}
          disabled={disabled}
          onChange={(e) => {
            onFieldChange(step.id, "code", e.target.value);
          }}
        />
      </div>
    </li>
  );
}

import type { StatusBadgeStatus } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";

type RunStepPublic = components["schemas"]["RunStepPublic"];
type StepOutcome = components["schemas"]["StepOutcome"];
type ArtifactPublic = components["schemas"]["ArtifactPublic"];

/** Rolled-up status for a case, derived from its steps. */
export type CaseRollup = "pass" | "fail" | "running" | "skipped" | "neutral";

/** Human-readable label for a step. Never a case id — falls back to type + order. */
export function stepTitle(step: RunStepPublic): string {
  const title = step.title?.trim();
  if (title) return title;
  const type = step.type?.trim() ?? "step";
  return `${type} · step ${step.step_order.toString()}`;
}

/** Small tag label for a step's type (action/assertion/navigation/wait/api). */
export function stepTypeLabel(type: string | null | undefined): string {
  const t = type?.trim();
  return t && t.length > 0 ? t : "step";
}

export function outcomeToBadge(outcome: StepOutcome): StatusBadgeStatus {
  switch (outcome) {
    case "PASS":
      return "pass";
    case "FAIL":
    case "ERROR":
      return "fail";
    case "SKIP":
      return "warn";
    default:
      return "neutral";
  }
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms.toString()}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m.toString()}m ${Math.round(s % 60).toString()}s`;
}

/** One test case's rolled-up view over the run's steps + artifacts. */
export interface CaseGroup {
  caseId: string;
  casePublicId: string;
  caseName: string;
  steps: RunStepPublic[];
  total: number;
  passed: number;
  failed: number;
  rollup: CaseRollup;
  durationMs: number;
  /** "frontend" when the case has any screenshot/video, else "api". */
  kind: "frontend" | "api";
  /** First failure message across the case's steps, if any. */
  firstFailure: string | null;
}

/** Statuses considered still in-flight for the running rollup. */
const RUNNING_OUTCOMES: ReadonlySet<StepOutcome> = new Set<StepOutcome>(["PENDING"]);

function rollupOf(steps: RunStepPublic[]): CaseRollup {
  if (steps.length === 0) return "neutral";
  if (steps.some((s) => s.outcome === "FAIL" || s.outcome === "ERROR")) return "fail";
  if (steps.some((s) => RUNNING_OUTCOMES.has(s.outcome))) return "running";
  if (steps.every((s) => s.outcome === "SKIP")) return "skipped";
  if (steps.every((s) => s.outcome === "PASS" || s.outcome === "SKIP")) return "pass";
  return "neutral";
}

/**
 * Group a run's steps into test cases, ordered by their first step's order.
 * `artifacts` is used only to infer frontend-vs-api per case (has media → frontend).
 */
export function groupStepsByCase(steps: RunStepPublic[], artifacts: ArtifactPublic[]): CaseGroup[] {
  const byCase = new Map<string, RunStepPublic[]>();
  const firstIndex = new Map<string, number>();
  steps.forEach((s, i) => {
    const list = byCase.get(s.case_id);
    if (list) {
      list.push(s);
    } else {
      byCase.set(s.case_id, [s]);
      firstIndex.set(s.case_id, i);
    }
  });

  // A case is "frontend" if any of its steps produced a screenshot/video.
  const mediaStepIds = new Set(
    artifacts
      .filter((a) => a.kind === "SCREENSHOT" || a.kind === "VIDEO")
      .map((a) => a.run_step_id),
  );

  const groups: CaseGroup[] = [];
  for (const [caseId, caseSteps] of byCase) {
    const ordered = [...caseSteps].sort((a, b) => a.step_order - b.step_order);
    const passed = ordered.filter((s) => s.outcome === "PASS").length;
    const failed = ordered.filter((s) => s.outcome === "FAIL" || s.outcome === "ERROR").length;
    const durationMs = ordered.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
    const hasMedia = ordered.some((s) => mediaStepIds.has(s.id));
    const failing = ordered.find((s) => s.outcome === "FAIL" || s.outcome === "ERROR");
    const first = ordered[0];
    groups.push({
      caseId,
      casePublicId: first?.case_public_id ?? caseId,
      caseName: first?.case_name?.trim() ?? first?.case_public_id ?? "Untitled case",
      steps: ordered,
      total: ordered.length,
      passed,
      failed,
      rollup: rollupOf(ordered),
      durationMs,
      kind: hasMedia ? "frontend" : "api",
      firstFailure: failing?.error_message?.trim() ?? null,
    });
  }

  groups.sort((a, b) => (firstIndex.get(a.caseId) ?? 0) - (firstIndex.get(b.caseId) ?? 0));
  return groups;
}

export function rollupLabel(rollup: CaseRollup): string {
  switch (rollup) {
    case "pass":
      return "PASS";
    case "fail":
      return "FAIL";
    case "running":
      return "RUNNING";
    case "skipped":
      return "SKIP";
    default:
      return "PENDING";
  }
}

export function rollupToBadge(rollup: CaseRollup): StatusBadgeStatus {
  switch (rollup) {
    case "pass":
      return "pass";
    case "fail":
      return "fail";
    case "running":
      return "running";
    case "skipped":
      return "warn";
    default:
      return "neutral";
  }
}

import type { StatusBadgeStatus } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";

type RunStatus = components["schemas"]["RunStatus"];
type StepOutcome = components["schemas"]["StepOutcome"];

/**
 * Map a run status onto the shared status palette. The narrowed return type is
 * a subset of `StatusBadgeStatus` that is also assignable to `SourceDotStatus`,
 * so call sites can feed either `<StatusBadge>` or `<SourceDot>`.
 */
export function statusToBadge(status: RunStatus): "pass" | "fail" | "warn" | "running" | "neutral" {
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

/** Map a step outcome onto the shared status-badge palette. */
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

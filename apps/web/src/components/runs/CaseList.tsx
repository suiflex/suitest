import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatDuration } from "@/lib/test-case-format";
import { cn } from "@/lib/utils";

import { rollupLabel, rollupToBadge, type CaseGroup } from "./case-grouping";

interface CaseListProps {
  groups: CaseGroup[];
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
}

/**
 * Master column of a run detail: one card per TEST CASE (not per step). Each
 * card shows the case's public id, title, rolled-up status, step counts,
 * duration, and a frontend/api kind tag.
 */
export function CaseList({
  groups,
  selectedCaseId,
  onSelectCase,
}: CaseListProps): React.ReactElement {
  if (groups.length === 0) {
    return (
      <div
        className="rounded-md border border-border bg-bg-elev-1 p-4 text-[12px] text-fg-4"
        data-testid="case-list-empty"
      >
        No test cases recorded yet.
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-1.5" data-testid="case-list">
      {groups.map((g) => {
        const selected = g.caseId === selectedCaseId;
        return (
          <li key={g.caseId}>
            <button
              type="button"
              onClick={() => {
                onSelectCase(g.caseId);
              }}
              data-testid="case-row"
              data-case-id={g.caseId}
              data-selected={selected ? "true" : undefined}
              className={cn(
                "flex w-full flex-col gap-1.5 rounded-md border border-border bg-bg-elev-1 p-3 text-left transition-colors hover:bg-bg-elev-2",
                selected && "border-accent/40 bg-accent/[0.06]",
              )}
            >
              <div className="flex items-center gap-2">
                <StatusBadge status={rollupToBadge(g.rollup)} label={rollupLabel(g.rollup)} />
                <span className="font-mono text-[10.5px] text-fg-5">{g.casePublicId}</span>
                <span
                  className="rounded bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-4"
                  data-testid="case-row-kind"
                >
                  {g.kind}
                </span>
              </div>
              <span className="truncate text-[12.5px] text-fg-1" data-testid="case-row-title">
                {g.caseName}
              </span>
              <div className="flex items-center gap-3 font-mono text-[10.5px] text-fg-4 tabular-nums">
                <span data-testid="case-row-counts">
                  {g.total} steps · {g.passed} passed
                  {g.failed > 0 ? <span className="text-red"> · {g.failed} failed</span> : null}
                </span>
                <span className="ml-auto">{formatDuration(g.durationMs)}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

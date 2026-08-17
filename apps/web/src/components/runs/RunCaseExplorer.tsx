import { useQuery } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CaseDetailPanel } from "@/components/runs/CaseDetailPanel";
import { CaseList } from "@/components/runs/CaseList";
import { groupStepsByCase } from "@/components/runs/case-grouping";
import { EmptyState } from "@/components/shared/EmptyState";
import { fetchRunArtifacts, fetchRunSteps } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useRunStream } from "@/lib/ws-client";

type RunStatus = components["schemas"]["RunStatus"];

interface RunCaseExplorerProps {
  /** Run id OR public_id — the endpoints resolve either. */
  runId: string;
  /** Run status, when the caller already has it — drives polling + empty copy. */
  status?: RunStatus | undefined;
}

/** Once a run reaches one of these, no further steps can appear. */
function isTerminal(status: RunStatus | undefined): boolean {
  return (
    status === "PASS" || status === "FAIL" || status === "ERROR" || status === "CANCELLED"
  );
}

/**
 * The TEST-CASE master-detail for a run: the flat step list is grouped into
 * test cases (left), and the selected case shows its steps + evidence tabs
 * (Preview/Code/Logs/Artifacts) on the right — TestSprite-style, NOT a raw step
 * dump. Shared by the full-page run route AND the /runs side panel so both give
 * the same video/code/screenshot experience.
 */
export function RunCaseExplorer({ runId, status }: RunCaseExplorerProps): React.ReactElement {
  // Poll until the run is terminal. The WS refetch below is the fast path, but
  // local mode publishes to a NullPublisher — no event ever reaches the browser,
  // so without polling the panel stayed empty until a manual reload (issue #109).
  const refetchInterval = isTerminal(status) ? false : 2000;
  const { data: stepsData, refetch: refetchSteps } = useQuery({
    queryKey: ["run-steps", runId] as const,
    queryFn: () => fetchRunSteps(runId),
    refetchInterval,
  });
  const { data: artifactsData, refetch: refetchArtifacts } = useQuery({
    queryKey: ["run-artifacts", runId] as const,
    queryFn: () => fetchRunArtifacts(runId),
    refetchInterval,
  });

  const steps = useMemo(() => stepsData?.items ?? [], [stepsData]);
  const artifacts = useMemo(() => artifactsData?.items ?? [], [artifactsData]);
  const groups = useMemo(() => groupStepsByCase(steps, artifacts), [steps, artifacts]);

  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  useEffect(() => {
    setSelectedCaseId(null);
  }, [runId]);

  // Default to the first FAILED case (triage-first), else the first case — once,
  // never overriding an explicit user pick.
  useEffect(() => {
    const first = groups[0];
    if (!first) return;
    setSelectedCaseId((cur) => {
      if (cur && groups.some((g) => g.caseId === cur)) return cur;
      const failing = groups.find((g) => g.rollup === "fail");
      return (failing ?? first).caseId;
    });
  }, [groups]);

  useRunStream(runId, (e) => {
    if (
      e.event === "run.step.started" ||
      e.event === "run.step.completed" ||
      e.event === "run.completed"
    ) {
      void refetchSteps();
      void refetchArtifacts();
    }
  });

  const selectedGroup = useMemo(
    () => groups.find((g) => g.caseId === selectedCaseId) ?? null,
    [groups, selectedCaseId],
  );

  if (groups.length === 0) {
    // Distinguish "hasn't run yet" from "ran and produced nothing" — the old
    // single message read as data loss whenever a run was merely queued.
    if (status === "QUEUED") {
      return (
        <EmptyState
          icon={ListChecks}
          title="Queued"
          subtitle="Waiting for a runner to pick this run up."
        />
      );
    }
    if (status === "RUNNING") {
      return (
        <EmptyState
          icon={ListChecks}
          title="Running"
          subtitle="Test cases appear here as their steps complete."
        />
      );
    }
    return (
      <EmptyState
        icon={ListChecks}
        title="No test cases recorded"
        subtitle="This run finished without executing any steps."
      />
    );
  }

  return (
    // Container query (not viewport): the explorer renders both full-page and
    // inside the /runs side panel, so column split keys off its own width.
    <div className="grid min-w-0 grid-cols-12 gap-4 @container">
      <div className="col-span-12 min-w-0 @3xl:col-span-4" data-testid="run-case-master">
        <CaseList
          groups={groups}
          selectedCaseId={selectedCaseId}
          onSelectCase={setSelectedCaseId}
        />
      </div>
      <div className="col-span-12 min-w-0 @3xl:col-span-8" data-testid="run-case-detail">
        {selectedGroup ? (
          <CaseDetailPanel runId={runId} group={selectedGroup} artifacts={artifacts} />
        ) : (
          <EmptyState
            icon={ListChecks}
            title="No test case selected"
            subtitle="Pick a test case from the list to see its steps and evidence."
          />
        )}
      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CaseDetailPanel } from "@/components/runs/CaseDetailPanel";
import { CaseList } from "@/components/runs/CaseList";
import { groupStepsByCase } from "@/components/runs/case-grouping";
import { EmptyState } from "@/components/shared/EmptyState";
import { fetchRunArtifacts, fetchRunSteps } from "@/lib/api-client";
import { useRunStream } from "@/lib/ws-client";

interface RunCaseExplorerProps {
  /** Run id OR public_id — the endpoints resolve either. */
  runId: string;
}

/**
 * The TEST-CASE master-detail for a run: the flat step list is grouped into
 * test cases (left), and the selected case shows its steps + evidence tabs
 * (Preview/Code/Logs/Artifacts) on the right — TestSprite-style, NOT a raw step
 * dump. Shared by the full-page run route AND the /runs side panel so both give
 * the same video/code/screenshot experience.
 */
export function RunCaseExplorer({ runId }: RunCaseExplorerProps): React.ReactElement {
  const { data: stepsData, refetch: refetchSteps } = useQuery({
    queryKey: ["run-steps", runId] as const,
    queryFn: () => fetchRunSteps(runId),
  });
  const { data: artifactsData, refetch: refetchArtifacts } = useQuery({
    queryKey: ["run-artifacts", runId] as const,
    queryFn: () => fetchRunArtifacts(runId),
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
    return (
      <EmptyState
        icon={ListChecks}
        title="No test cases recorded"
        subtitle="This run has no recorded steps yet."
      />
    );
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-4" data-testid="run-case-master">
        <CaseList
          groups={groups}
          selectedCaseId={selectedCaseId}
          onSelectCase={setSelectedCaseId}
        />
      </div>
      <div className="col-span-12 lg:col-span-8" data-testid="run-case-detail">
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

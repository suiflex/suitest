import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";

import { RunCaseExplorer } from "@/components/runs/RunCaseExplorer";
import { RunSummaryCard } from "@/components/runs/RunSummaryCard";
import { fetchRun } from "@/lib/api-client";

export const Route = createFileRoute("/_app/runs_/$runId")({
  component: RunDetailPage,
  staticData: { title: "Run detail" },
});

export function RunDetailPage(): React.ReactElement {
  const { runId } = Route.useParams();

  const { data: run } = useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => fetchRun(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const terminal =
        status === "PASS" || status === "FAIL" || status === "ERROR" || status === "CANCELLED";
      return terminal ? false : 2000;
    },
  });

  return (
    <section className="flex flex-col gap-4" data-testid="run-detail-page">
      <div className="flex justify-end">
        <Link
          to="/runs/$runId/replay"
          params={{ runId }}
          className="rounded-md border border-border bg-bg-elev-1 px-2.5 py-1 text-[12.5px] text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          data-testid="run-replay-link"
        >
          ⏱ Time-travel replay
        </Link>
      </div>

      <RunSummaryCard run={run} />

      {/* TEST CASE master-detail — the primary run view (shared with the panel). */}
      <RunCaseExplorer runId={runId} />
    </section>
  );
}

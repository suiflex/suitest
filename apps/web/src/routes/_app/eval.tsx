import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Database, Lock, Play, TrendingDown, TrendingUp } from "lucide-react";

import { EmptyState } from "@/components/shared/EmptyState";
import {
  type EvalRunListItem,
  ApiError,
  createEvalRun,
  fetchEvalFixtures,
  fetchEvalRuns,
} from "@/lib/api-client";

export const Route = createFileRoute("/_app/eval")({
  component: EvalPage,
  staticData: { title: "Eval suite" },
});

/**
 * Eval suite dashboard (M5-2). Three deterministic / ZERO-tier panels:
 * golden datasets (what the weekly CI scores), a run trigger, and the
 * score-regression dashboard (pass-rate over the last runs). ADMIN+ only —
 * the backend 403s for other roles and we render an access notice.
 */
export function EvalPage(): React.ReactElement {
  const qc = useQueryClient();

  const fixtures = useQuery({
    queryKey: ["eval-fixtures"] as const,
    queryFn: fetchEvalFixtures,
    retry: false,
  });
  const runs = useQuery({
    queryKey: ["eval-runs"] as const,
    queryFn: () => fetchEvalRuns(),
    retry: false,
  });

  const runEval = useMutation({
    mutationFn: () => createEvalRun("default"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["eval-runs"] });
    },
  });

  const forbidden =
    (fixtures.error instanceof ApiError && fixtures.error.status === 403) ||
    (runs.error instanceof ApiError && runs.error.status === 403);

  if (forbidden) {
    return (
      <div className="p-4" data-testid="eval-forbidden">
        <EmptyState
          icon={Lock}
          title="Admin access required"
          subtitle="The eval suite is available to workspace admins and owners."
        />
      </div>
    );
  }

  const runList = runs.data ?? [];
  const totalFixtures = (fixtures.data ?? []).reduce((acc, s) => acc + s.fixtures, 0);

  return (
    <div className="flex flex-col gap-4 p-4" data-testid="eval-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[15px] font-semibold text-fg-1">Eval suite</h1>
          <p className="text-[12.5px] text-fg-3">
            Deterministic golden-dataset scoring · weekly CI gate
          </p>
        </div>
        <button
          type="button"
          onClick={() => runEval.mutate()}
          disabled={runEval.isPending}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-3 py-1.5 text-[12.5px] font-medium text-fg-1 hover:bg-bg-elev-2 disabled:opacity-50"
          data-testid="eval-run-button"
        >
          <Play className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
          {runEval.isPending ? "Running…" : "Run eval"}
        </button>
      </div>

      {/* Golden datasets */}
      <section
        className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
        data-testid="eval-datasets"
      >
        <div className="mb-3 flex items-center gap-2">
          <Database className="h-4 w-4 text-fg-4" aria-hidden="true" />
          <h2 className="text-[13px] font-medium text-fg-1">Golden datasets</h2>
          <span className="font-mono text-[11.5px] text-fg-4">{totalFixtures} fixtures</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {(fixtures.data ?? []).map((s) => (
            <div
              key={s.suite}
              className="rounded-md border border-border bg-bg-elev-2 p-3"
              data-testid={`eval-dataset-${s.suite}`}
            >
              <div className="text-[12.5px] font-medium text-fg-1">{s.suite}</div>
              <div className="mt-1 font-mono text-[18px] text-accent">{s.fixtures}</div>
              <div className="text-[11px] text-fg-4">fixtures</div>
            </div>
          ))}
        </div>
      </section>

      {/* Score-regression dashboard */}
      <section
        className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
        data-testid="eval-regression"
      >
        <h2 className="mb-3 text-[13px] font-medium text-fg-1">Score regression</h2>
        {runList.length === 0 ? (
          <EmptyState
            icon={TrendingUp}
            title="No eval runs yet"
            subtitle="Run the eval suite to start tracking score over time."
          />
        ) : (
          <RegressionChart runs={runList} />
        )}
      </section>
    </div>
  );
}

/**
 * Pass-rate bars over time (newest-first list rendered oldest→newest). Each bar
 * height is the run's score; the delta vs. the previous run flags regressions.
 */
function RegressionChart({ runs }: { runs: EvalRunListItem[] }): React.ReactElement {
  // API returns newest-first; chart reads left→right oldest→newest.
  const ordered = [...runs].reverse();
  return (
    <div data-testid="eval-regression-chart">
      <div className="flex items-end gap-2" style={{ height: 160 }}>
        {ordered.map((run, i) => {
          const prev = i > 0 ? ordered[i - 1] : undefined;
          const delta = prev ? run.scorePct - prev.scorePct : 0;
          const regressed = delta < 0;
          return (
            <div key={run.id} className="flex flex-1 flex-col items-center justify-end gap-1">
              <span className="font-mono text-[10px] text-fg-4">{run.scorePct}%</span>
              <div
                className={`w-full rounded-t-sm ${regressed ? "bg-red" : "bg-accent"}`}
                style={{ height: `${Math.max(run.scorePct, 2)}%` }}
                data-testid="eval-bar"
                data-regressed={regressed}
                title={`${run.passed}/${run.fixturesCount} passed`}
              />
            </div>
          );
        })}
      </div>
      <table className="mt-4 w-full text-left text-[12px]">
        <thead className="text-fg-4">
          <tr>
            <th className="py-1 font-medium">Run</th>
            <th className="py-1 font-medium">Suite</th>
            <th className="py-1 font-medium">Score</th>
            <th className="py-1 font-medium">Passed</th>
            <th className="py-1 font-medium">Δ</th>
          </tr>
        </thead>
        <tbody className="font-mono text-fg-3">
          {runs.map((run, i) => {
            const next = runs[i + 1];
            const delta = next ? run.scorePct - next.scorePct : 0;
            return (
              <tr key={run.id} className="border-t border-border">
                <td className="py-1">{new Date(run.runAt).toLocaleString()}</td>
                <td className="py-1">{run.suiteName}</td>
                <td className="py-1">{run.scorePct}%</td>
                <td className="py-1">
                  {run.passed}/{run.fixturesCount}
                </td>
                <td className="py-1">
                  {delta === 0 ? (
                    <span className="text-fg-5">—</span>
                  ) : delta < 0 ? (
                    <span className="inline-flex items-center gap-1 text-red">
                      <TrendingDown className="h-3 w-3" aria-hidden="true" />
                      {delta.toFixed(1)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-accent">
                      <TrendingUp className="h-3 w-3" aria-hidden="true" />+{delta.toFixed(1)}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

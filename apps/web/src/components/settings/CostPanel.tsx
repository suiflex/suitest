import { useQuery } from "@tanstack/react-query";

import { fetchWorkspaceCost } from "@/lib/api-client";

interface CostPanelProps {
  workspaceId: string;
}

function usd(value: number): string {
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}

/** Compact LLM spend summary + soft daily-budget banner (M3-14). */
export function CostPanel({ workspaceId }: CostPanelProps): React.ReactElement {
  const query = useQuery({
    queryKey: ["workspace", workspaceId, "cost"],
    queryFn: () => fetchWorkspaceCost(workspaceId),
  });

  if (query.isLoading || !query.data) {
    return (
      <section className="max-w-xl text-[13px] text-fg-3" data-testid="cost-panel">
        Loading cost…
      </section>
    );
  }

  const cost = query.data;

  return (
    <section className="max-w-xl space-y-4" data-testid="cost-panel">
      <div className="space-y-1">
        <h2 className="text-[15px] font-semibold text-fg-1">LLM cost</h2>
        <p className="text-[13px] text-fg-3">
          Spend across agent sessions over the last {cost.windowDays} days.
        </p>
      </div>

      {cost.budget.overBudget && cost.budget.alert ? (
        <p
          role="alert"
          className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12.5px] text-amber"
          data-testid="cost-budget-alert"
        >
          {cost.budget.alert}
        </p>
      ) : null}

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border border-border bg-bg-elev-1 p-3">
          <p className="text-[11px] text-fg-4">Total spend</p>
          <p className="mt-1 font-mono text-[16px] text-fg-1">{usd(cost.totalCostUsd)}</p>
        </div>
        <div className="rounded-lg border border-border bg-bg-elev-1 p-3">
          <p className="text-[11px] text-fg-4">Today / cap</p>
          <p className="mt-1 font-mono text-[16px] text-fg-1">
            {usd(cost.budget.todaySpendUsd)}
            <span className="text-[12px] text-fg-4"> / {usd(cost.budget.dailyCapUsd)}</span>
          </p>
        </div>
        <div className="rounded-lg border border-border bg-bg-elev-1 p-3">
          <p className="text-[11px] text-fg-4">Sessions</p>
          <p className="mt-1 font-mono text-[16px] text-fg-1">{cost.sessionCount}</p>
        </div>
      </div>

      {cost.byProvider.length > 0 ? (
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="text-left text-fg-4">
              <th className="pb-1 font-medium">Provider</th>
              <th className="pb-1 text-right font-medium">Cost</th>
              <th className="pb-1 text-right font-medium">Tokens</th>
              <th className="pb-1 text-right font-medium">Sessions</th>
            </tr>
          </thead>
          <tbody>
            {cost.byProvider.map((p) => (
              <tr key={p.provider} className="border-t border-border">
                <td className="py-1.5 text-fg-1">{p.provider}</td>
                <td className="py-1.5 text-right font-mono text-fg-1">{usd(p.costUsd)}</td>
                <td className="py-1.5 text-right font-mono text-fg-3">
                  {(p.tokensIn + p.tokensOut).toLocaleString()}
                </td>
                <td className="py-1.5 text-right font-mono text-fg-3">{p.sessions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-[12.5px] text-fg-4">No agent sessions yet.</p>
      )}

      {cost.byKind.length > 0 ? (
        <div className="space-y-1.5" data-testid="cost-by-kind">
          <h3 className="text-[12px] font-medium text-fg-3">By generation kind</h3>
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-fg-4">
                <th className="pb-1 font-medium">Kind</th>
                <th className="pb-1 text-right font-medium">Cost</th>
                <th className="pb-1 text-right font-medium">Sessions</th>
              </tr>
            </thead>
            <tbody>
              {cost.byKind.map((k) => (
                <tr key={k.kind} className="border-t border-border">
                  <td className="py-1.5 text-fg-1">{k.kind}</td>
                  <td className="py-1.5 text-right font-mono text-fg-3">{usd(k.costUsd)}</td>
                  <td className="py-1.5 text-right font-mono text-fg-3">{k.sessions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

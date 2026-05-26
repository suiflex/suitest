import { createFileRoute } from "@tanstack/react-router";

import { useCapabilities } from "@/stores/use-capabilities";

function Dashboard(): React.ReactElement {
  const data = useCapabilities((s) => s.data);
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Dashboard</h2>
      <p className="text-fg-3">
        Empty dashboard (M0 skeleton). Full KPIs ship in M1.
      </p>
      {data ? (
        <pre className="rounded-md border border-border bg-elev-1 p-4 font-mono text-xs text-fg-3">
          tier={data.tier} provider={data.llm?.provider ?? "none"}
        </pre>
      ) : null}
    </section>
  );
}

export const Route = createFileRoute("/dashboard")({ component: Dashboard });

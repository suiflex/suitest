import { createFileRoute } from "@tanstack/react-router";

import { useCapabilities } from "@/stores/use-capabilities";

function Dashboard(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Dashboard</h2>
      <p className="text-fg-3">
        Empty dashboard (M1b skeleton). Full KPI widgets ship in Task 6.
      </p>
      {capabilities ? (
        <pre className="rounded-md border border-border bg-elev-1 p-4 font-mono text-xs text-fg-3">
          tier={capabilities.tier} provider={capabilities.llm?.provider ?? "none"}
        </pre>
      ) : null}
    </section>
  );
}

export const Route = createFileRoute("/_app/dashboard")({ component: Dashboard });

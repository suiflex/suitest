import { createFileRoute } from "@tanstack/react-router";

import { useCapabilities } from "@/stores/use-capabilities";

function Home(): React.ReactElement {
  const { data, isLoading, error } = useCapabilities();
  if (isLoading) return <p className="text-fg-3">Loading capabilities…</p>;
  if (error) return <p className="text-red">Error: {error}</p>;
  if (!data) return <p className="text-fg-4">Awaiting capabilities…</p>;
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Welcome to Suitest</h2>
      <p className="text-fg-3">
        Running in <span className="font-mono text-fg-1">{data.tier}</span> tier.
      </p>
    </section>
  );
}

export const Route = createFileRoute("/")({ component: Home });

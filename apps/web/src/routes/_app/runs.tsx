import { createFileRoute } from "@tanstack/react-router";

function Runs(): React.ReactElement {
  return (
    <section className="space-y-2 px-6 py-8">
      <h2 className="text-[18px] font-semibold tracking-[-.01em]">Test Runs</h2>
      <p className="text-fg-3">Test Runs screen is wired up in Task 7.</p>
    </section>
  );
}

export const Route = createFileRoute("/_app/runs")({
  component: Runs,
  staticData: { title: "Test Runs" },
});

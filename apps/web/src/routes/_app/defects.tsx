import { createFileRoute } from "@tanstack/react-router";

function Defects(): React.ReactElement {
  return (
    <section className="space-y-2 px-6 py-8">
      <h2 className="text-[18px] font-semibold tracking-[-.01em]">Defects</h2>
      <p className="text-fg-3">Defects screen is wired up in Task 7.</p>
    </section>
  );
}

export const Route = createFileRoute("/_app/defects")({
  component: Defects,
  staticData: { title: "Defects" },
});

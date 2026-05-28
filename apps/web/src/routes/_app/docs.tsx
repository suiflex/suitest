import { createFileRoute } from "@tanstack/react-router";

function Docs(): React.ReactElement {
  return (
    <section className="space-y-2 px-6 py-8">
      <h2 className="text-[18px] font-semibold tracking-[-.01em]">Documents</h2>
      <p className="text-fg-3">Documents browser is wired up in Task 7.</p>
    </section>
  );
}

export const Route = createFileRoute("/_app/docs")({
  component: Docs,
  staticData: { title: "Documents" },
});

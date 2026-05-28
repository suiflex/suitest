import { createFileRoute } from "@tanstack/react-router";

function Inbox(): React.ReactElement {
  return (
    <section className="space-y-2 px-6 py-8">
      <h2 className="text-[18px] font-semibold tracking-[-.01em]">Inbox</h2>
      <p className="text-fg-3">Inbox screen lands in a later milestone.</p>
    </section>
  );
}

export const Route = createFileRoute("/_app/inbox")({
  component: Inbox,
  staticData: { title: "Inbox" },
});

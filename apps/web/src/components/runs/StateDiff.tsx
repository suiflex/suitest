import type { StateChange } from "@/lib/api-client";

/**
 * State-delta diff viewer (M5-1). Renders the key-level changes between a replay
 * step and the previous step: added keys in accent, removed in red, changed show
 * before → after. Deterministic, tier-agnostic — purely run data.
 */
export function StateDiff({ changes }: { changes: StateChange[] }): React.ReactElement {
  if (changes.length === 0) {
    return (
      <p className="text-[12px] text-fg-4" data-testid="state-diff-empty">
        No state change at this step.
      </p>
    );
  }
  return (
    <ul className="space-y-1 font-mono text-[11.5px]" data-testid="state-diff">
      {changes.map((c) => (
        <li key={`${c.op}:${c.path}`} className="flex gap-2" data-op={c.op}>
          <span className={`w-14 shrink-0 ${OP_COLOR[c.op]}`}>{OP_LABEL[c.op]}</span>
          <span className="flex-1 break-all">
            <span className="text-fg-1">{c.path}</span>
            {c.op === "added" ? <span className="ml-2 text-accent">{c.after}</span> : null}
            {c.op === "removed" ? (
              <span className="ml-2 text-red line-through">{c.before}</span>
            ) : null}
            {c.op === "changed" ? (
              <span className="ml-2">
                <span className="text-red line-through">{c.before}</span>
                <span className="mx-1 text-fg-4">→</span>
                <span className="text-accent">{c.after}</span>
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

const OP_LABEL: Record<StateChange["op"], string> = {
  added: "+ add",
  removed: "− del",
  changed: "~ chg",
};

const OP_COLOR: Record<StateChange["op"], string> = {
  added: "text-accent",
  removed: "text-red",
  changed: "text-amber",
};

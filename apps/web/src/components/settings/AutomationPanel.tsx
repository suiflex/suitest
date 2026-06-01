import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  type AutonomyLevel,
  type AutonomyState,
  fetchAutonomy,
  putAutonomy,
} from "@/lib/api-client";

/** The four autonomy levels with UI copy (mirrors docs/AUTONOMY.md §2 + §7). */
const LEVELS: { id: AutonomyLevel; name: string; blurb: string; hint: string }[] = [
  {
    id: "manual",
    name: "Manual",
    blurb: "Human-only workflow. No AI actions; agent UI hidden.",
    hint: "Air-gapped / no LLM",
  },
  {
    id: "assist",
    name: "Assist",
    blurb: "AI proposes; a human approves every artifact and agentic step.",
    hint: "Most teams",
  },
  {
    id: "semi_auto",
    name: "Semi-auto",
    blurb: "P2/P3 auto-approve; P0/P1 gated. Auto-categorize diagnoses.",
    hint: "Trusted suites",
  },
  {
    id: "auto",
    name: "Auto",
    blurb: "Hands-off CI. Agent acts; humans review the audit log.",
    hint: "Production CI",
  },
];

/** v2.x / integration-gated keys render as disabled toggles. */
const DISABLED_KEYS = new Set(["auto_pr_fix", "exec_self_heal_enabled"]);

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface AutomationPanelProps {
  workspaceId: string;
  /** ADMIN+ may write; others see the read-only state. */
  canWrite: boolean;
}

export function AutomationPanel({
  workspaceId,
  canWrite,
}: AutomationPanelProps): React.ReactElement {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["workspace", workspaceId, "autonomy"],
    queryFn: () => fetchAutonomy(workspaceId),
  });

  const [level, setLevel] = useState<AutonomyLevel>("manual");
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Seed local state once the server state lands (and after a successful save
  // re-seeds via invalidation → refetch).
  useEffect(() => {
    if (query.data) {
      setLevel(query.data.level);
      setOverrides(query.data.overrides);
    }
  }, [query.data]);

  const data: AutonomyState | undefined = query.data;
  const isZero = data?.tier === "ZERO";

  const saveMutation = useMutation({
    mutationFn: () => putAutonomy(workspaceId, { level, overrides }),
    onSuccess: () => {
      setError(null);
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "autonomy"] });
      void queryClient.invalidateQueries({ queryKey: ["capabilities"] });
    },
    onError: () => setError("Could not update autonomy. ZERO tier only allows Manual."),
  });

  if (query.isLoading || !data) {
    return (
      <section className="max-w-2xl text-[13px] text-fg-3" data-testid="automation-panel">
        Loading automation settings…
      </section>
    );
  }

  const toggleOverride = (key: string, value: boolean): void => {
    setSaved(false);
    setOverrides((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <section className="max-w-2xl space-y-6" data-testid="automation-panel">
      <div className="space-y-1">
        <h2 className="text-[15px] font-semibold text-fg-1">Automation</h2>
        <p className="text-[13px] text-fg-3">
          How much the agent does without asking. Tier: <span className="text-fg-1">{data.tier}</span>
          {isZero ? " — configure an LLM to unlock higher autonomy." : null}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Autonomy level">
        {LEVELS.map((lvl) => {
          const selected = level === lvl.id;
          const disabled = !canWrite || (isZero && lvl.id !== "manual");
          return (
            <button
              key={lvl.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              data-testid={`autonomy-level-${lvl.id}`}
              onClick={() => {
                setSaved(false);
                setLevel(lvl.id);
              }}
              className={`rounded-lg border p-4 text-left transition ${
                selected ? "border-accent bg-accent/5" : "border-border bg-bg-elev-1"
              } ${disabled ? "cursor-not-allowed opacity-50" : "hover:border-fg-4"}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-[14px] font-medium text-fg-1">{lvl.name}</span>
                {selected ? <span className="text-[11px] font-medium text-accent">Active</span> : null}
              </div>
              <p className="mt-1 text-[12px] text-fg-3">{lvl.blurb}</p>
              <p className="mt-2 text-[11px] text-fg-4">For: {lvl.hint}</p>
            </button>
          );
        })}
      </div>

      <details className="rounded-lg border border-border bg-bg-elev-1 p-4">
        <summary className="cursor-pointer text-[13px] font-medium text-fg-1">
          Advanced overrides
        </summary>
        <p className="mt-2 text-[12px] text-fg-4">
          Flip individual behaviors within the selected level. Effective value shown when unchanged.
        </p>
        <ul className="mt-3 space-y-2">
          {data.knownOverrideKeys.map((key) => {
            const overridden = key in overrides;
            const value = overridden ? overrides[key] : data.effective[key];
            const keyDisabled = !canWrite || isZero || DISABLED_KEYS.has(key);
            return (
              <li key={key} className="flex items-center justify-between gap-3">
                <span className="text-[12.5px] text-fg-1">
                  {humanize(key)}
                  {DISABLED_KEYS.has(key) ? (
                    <span className="ml-2 text-[11px] text-fg-4">(coming soon)</span>
                  ) : null}
                </span>
                <input
                  type="checkbox"
                  checked={Boolean(value)}
                  disabled={keyDisabled}
                  data-testid={`autonomy-override-${key}`}
                  onChange={(e) => toggleOverride(key, e.target.checked)}
                  className="h-4 w-4 accent-accent disabled:opacity-40"
                />
              </li>
            );
          })}
        </ul>
      </details>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
        >
          {error}
        </p>
      ) : null}
      {saved ? (
        <p
          role="status"
          className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-[12.5px] text-accent"
        >
          Automation settings saved.
        </p>
      ) : null}

      {canWrite ? (
        <button
          type="button"
          disabled={saveMutation.isPending}
          data-testid="autonomy-save"
          onClick={() => saveMutation.mutate()}
          className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saveMutation.isPending ? "Saving…" : "Save automation"}
        </button>
      ) : null}
    </section>
  );
}

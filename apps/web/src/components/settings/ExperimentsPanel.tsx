import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { useState } from "react";

import {
  type ExperimentVariantStats,
  type PromptExperiment,
  createPromptExperiment,
  fetchPromptExperiments,
  fetchPromptDetail,
  fetchPrompts,
  stopPromptExperiment,
} from "@/lib/api-client";

/**
 * Prompt A/B testing harness (M5-4). Runs two variants of a prompt (file default
 * or a fork) against each other, routing impressions by a split and tracking
 * conversion per variant so a winner emerges. LLM-gated upstream.
 */
export function ExperimentsPanel({ canWrite }: { canWrite: boolean }): React.ReactElement {
  const qc = useQueryClient();
  const experiments = useQuery({
    queryKey: ["prompt-experiments"] as const,
    queryFn: fetchPromptExperiments,
  });
  const stop = useMutation({
    mutationFn: (id: string) => stopPromptExperiment(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["prompt-experiments"] }),
  });

  return (
    <section className="space-y-3" data-testid="experiments-panel">
      <div>
        <h2 className="text-[15px] font-semibold text-fg-1">A/B testing</h2>
        <p className="text-[12.5px] text-fg-3">
          Compare two prompt variants and let conversion pick the winner.
        </p>
      </div>

      {canWrite ? <CreateExperimentForm /> : null}

      <ul className="space-y-2" data-testid="experiments-list">
        {(experiments.data ?? []).length === 0 ? (
          <li className="rounded-md border border-dashed border-border p-4 text-center text-[12.5px] text-fg-4">
            No experiments yet.
          </li>
        ) : (
          (experiments.data ?? []).map((exp) => (
            <ExperimentRow
              key={exp.id}
              exp={exp}
              canWrite={canWrite}
              onStop={() => stop.mutate(exp.id)}
            />
          ))
        )}
      </ul>
    </section>
  );
}

function ExperimentRow({
  exp,
  canWrite,
  onStop,
}: {
  exp: PromptExperiment;
  canWrite: boolean;
  onStop: () => void;
}): React.ReactElement {
  return (
    <li
      className="rounded-md border border-border bg-bg-elev-1 p-3"
      data-testid={`experiment-${exp.id}`}
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-[12.5px] text-fg-1">{exp.promptName}</span>
        <span
          className={`rounded-sm px-1.5 text-[10px] font-medium ${
            exp.status === "active" ? "bg-accent/15 text-accent" : "bg-bg-elev-3 text-fg-4"
          }`}
        >
          {exp.status}
        </span>
        <span className="text-[11px] text-fg-4">{exp.splitPct}% → B</span>
        {canWrite && exp.status === "active" ? (
          <button
            type="button"
            onClick={onStop}
            className="ml-auto rounded-sm border border-border px-2 py-0.5 text-[11px] text-fg-3 hover:bg-bg-elev-2"
            data-testid={`experiment-stop-${exp.id}`}
          >
            Stop
          </button>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <VariantCard stats={exp.variantA} winner={exp.winner === "A"} />
        <VariantCard stats={exp.variantB} winner={exp.winner === "B"} />
      </div>
    </li>
  );
}

function VariantCard({
  stats,
  winner,
}: {
  stats: ExperimentVariantStats;
  winner: boolean;
}): React.ReactElement {
  return (
    <div
      className={`rounded-md border p-2.5 ${winner ? "border-accent/50 bg-accent/5" : "border-border bg-bg-elev-2"}`}
      data-testid={`variant-${stats.variant}`}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-[12px] font-medium text-fg-1">Variant {stats.variant}</span>
        <span className="text-[10px] text-fg-4">{stats.overrideId ? "fork" : "default"}</span>
        {winner ? <Trophy className="ml-auto h-3.5 w-3.5 text-accent" aria-label="winner" /> : null}
      </div>
      <div className="mt-1 font-mono text-[16px] text-fg-1">{stats.conversionPct}%</div>
      <div className="text-[11px] text-fg-4">
        {stats.successes}/{stats.impressions} converted
      </div>
    </div>
  );
}

function CreateExperimentForm(): React.ReactElement {
  const qc = useQueryClient();
  const prompts = useQuery({ queryKey: ["prompts"] as const, queryFn: fetchPrompts });
  const [promptName, setPromptName] = useState("");
  const [variantB, setVariantB] = useState("");
  const [split, setSplit] = useState(50);

  const detail = useQuery({
    queryKey: ["prompt", promptName] as const,
    queryFn: () => fetchPromptDetail(promptName),
    enabled: promptName !== "",
  });

  const create = useMutation({
    mutationFn: () =>
      createPromptExperiment({
        prompt_name: promptName,
        variant_a_override_id: null, // A = file default
        variant_b_override_id: variantB || null,
        split_pct: split,
      }),
    onSuccess: () => {
      setPromptName("");
      setVariantB("");
      setSplit(50);
      void qc.invalidateQueries({ queryKey: ["prompt-experiments"] });
    },
  });

  const forks = detail.data?.forks ?? [];

  return (
    <div
      className="space-y-2 rounded-md border border-border bg-bg-elev-1 p-3"
      data-testid="experiment-create"
    >
      <div className="text-[11px] uppercase tracking-wide text-fg-5">New experiment</div>
      <select
        value={promptName}
        onChange={(e) => setPromptName(e.target.value)}
        className="w-full rounded-md border border-border bg-bg-elev-1 px-2.5 py-1.5 text-[12.5px] text-fg-1"
        data-testid="experiment-prompt-select"
      >
        <option value="">Select a prompt…</option>
        {(prompts.data ?? []).map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>

      {promptName ? (
        <>
          <label className="block text-[11px] text-fg-4">Variant B (vs. file default as A)</label>
          <select
            value={variantB}
            onChange={(e) => setVariantB(e.target.value)}
            className="w-full rounded-md border border-border bg-bg-elev-1 px-2.5 py-1.5 text-[12.5px] text-fg-1"
            data-testid="experiment-variant-b-select"
          >
            <option value="">Select a fork for B…</option>
            {forks.map((f) => (
              <option key={f.id} value={f.id}>
                v{f.forkVersion} {f.label ? `· ${f.label}` : ""}
              </option>
            ))}
          </select>
          <label className="block text-[11px] text-fg-4">Split to B: {split}%</label>
          <input
            type="range"
            min={0}
            max={100}
            value={split}
            onChange={(e) => setSplit(Number(e.target.value))}
            className="w-full accent-accent"
            data-testid="experiment-split"
          />
          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending || variantB === ""}
            className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
            data-testid="experiment-create-button"
          >
            {create.isPending ? "Starting…" : "Start A/B test"}
          </button>
        </>
      ) : null}
    </div>
  );
}

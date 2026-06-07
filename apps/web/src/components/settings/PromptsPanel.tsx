import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  type PromptFork,
  activatePromptFork,
  createPromptFork,
  deletePromptFork,
  fetchPromptDetail,
  fetchPrompts,
} from "@/lib/api-client";

/**
 * Workspace prompt forks (M5-3). Lists the file-based default prompts, lets an
 * admin fork one (DB override that wins over the file default), and manage the
 * fork history (activate a version / delete). LLM-gated upstream — surfaced
 * inside the LLM settings tab.
 */
export function PromptsPanel({ canWrite }: { canWrite: boolean }): React.ReactElement {
  const [selected, setSelected] = useState<string | null>(null);
  const prompts = useQuery({ queryKey: ["prompts"] as const, queryFn: fetchPrompts });

  return (
    <section className="space-y-3" data-testid="prompts-panel">
      <div>
        <h2 className="text-[15px] font-semibold text-fg-1">Prompt forks</h2>
        <p className="text-[12.5px] text-fg-3">
          Override the built-in default prompts for this workspace. The file default is always the
          fallback.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[220px_1fr]">
        <ul className="space-y-1" data-testid="prompts-list">
          {(prompts.data ?? []).map((p) => (
            <li key={p.name}>
              <button
                type="button"
                onClick={() => setSelected(p.name)}
                className={`flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left text-[12.5px] ${
                  selected === p.name
                    ? "border-accent/40 bg-bg-elev-2 text-fg-1"
                    : "border-border bg-bg-elev-1 text-fg-3 hover:bg-bg-elev-2"
                }`}
                data-testid={`prompt-item-${p.name}`}
              >
                <span className="truncate font-mono">{p.name}</span>
                {p.hasActiveFork ? (
                  <span className="ml-2 shrink-0 rounded-sm bg-violet/15 px-1.5 text-[10px] font-medium text-violet">
                    fork v{p.activeForkVersion}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
        {selected ? (
          <PromptDetailPanel name={selected} canWrite={canWrite} />
        ) : (
          <div className="rounded-md border border-dashed border-border p-6 text-center text-[12.5px] text-fg-4">
            Select a prompt to view its default and forks.
          </div>
        )}
      </div>
    </section>
  );
}

function PromptDetailPanel({
  name,
  canWrite,
}: {
  name: string;
  canWrite: boolean;
}): React.ReactElement {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["prompt", name] as const,
    queryFn: () => fetchPromptDetail(name),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [label, setLabel] = useState("");

  const invalidate = (): void => {
    void qc.invalidateQueries({ queryKey: ["prompt", name] });
    void qc.invalidateQueries({ queryKey: ["prompts"] });
  };

  const create = useMutation({
    mutationFn: () =>
      createPromptFork(name, label ? { content: draft ?? "", label } : { content: draft ?? "" }),
    onSuccess: () => {
      setDraft(null);
      setLabel("");
      invalidate();
    },
  });
  const activate = useMutation({
    mutationFn: (id: string) => activatePromptFork(id),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deletePromptFork(id),
    onSuccess: invalidate,
  });

  if (!detail.data) {
    return <div className="text-[12.5px] text-fg-4">Loading…</div>;
  }
  const defaultContent = detail.data.defaultContent;

  return (
    <div className="space-y-4" data-testid="prompt-detail">
      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-fg-5">File default</div>
        <pre className="max-h-40 overflow-auto rounded-md border border-border bg-bg-elev-2 p-2.5 font-mono text-[11px] text-fg-3 whitespace-pre-wrap">
          {defaultContent}
        </pre>
      </div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-fg-5">Forks</div>
        {detail.data.forks.length === 0 ? (
          <p className="text-[12px] text-fg-4">No forks yet.</p>
        ) : (
          <ul className="space-y-1.5" data-testid="prompt-forks">
            {detail.data.forks.map((f) => (
              <ForkRow
                key={f.id}
                fork={f}
                canWrite={canWrite}
                onActivate={() => activate.mutate(f.id)}
                onDelete={() => remove.mutate(f.id)}
              />
            ))}
          </ul>
        )}
      </div>

      {canWrite ? (
        <div className="space-y-2" data-testid="prompt-fork-editor">
          <div className="text-[11px] uppercase tracking-wide text-fg-5">New fork</div>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label (optional)"
            className="w-full rounded-md border border-border bg-bg-elev-1 px-2.5 py-1.5 text-[12.5px] text-fg-1"
          />
          <textarea
            value={draft ?? defaultContent}
            onChange={(e) => setDraft(e.target.value)}
            rows={8}
            className="w-full rounded-md border border-border bg-bg-elev-1 p-2.5 font-mono text-[11.5px] text-fg-1"
            data-testid="prompt-fork-textarea"
          />
          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending || (draft ?? defaultContent).trim().length === 0}
            className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
            data-testid="prompt-fork-save"
          >
            {create.isPending ? "Saving…" : "Create & activate fork"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ForkRow({
  fork,
  canWrite,
  onActivate,
  onDelete,
}: {
  fork: PromptFork;
  canWrite: boolean;
  onActivate: () => void;
  onDelete: () => void;
}): React.ReactElement {
  return (
    <li className="flex items-center gap-2 rounded-md border border-border bg-bg-elev-1 px-2.5 py-1.5 text-[12px]">
      <span className="font-mono text-fg-1">v{fork.forkVersion}</span>
      {fork.label ? <span className="text-fg-3">{fork.label}</span> : null}
      {fork.isActive ? (
        <span className="inline-flex items-center gap-1 rounded-sm bg-accent/15 px-1.5 text-[10px] font-medium text-accent">
          <Check className="h-3 w-3" aria-hidden="true" /> active
        </span>
      ) : null}
      <span className="ml-auto font-mono text-[10px] text-fg-5">{fork.hash.slice(0, 8)}</span>
      {canWrite && !fork.isActive ? (
        <button
          type="button"
          onClick={onActivate}
          className="rounded-sm border border-border px-1.5 py-0.5 text-[11px] text-fg-3 hover:bg-bg-elev-2"
          data-testid={`prompt-fork-activate-${fork.id}`}
        >
          Activate
        </button>
      ) : null}
      {canWrite ? (
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete fork"
          className="rounded-sm border border-border p-1 text-fg-4 hover:bg-bg-elev-2 hover:text-red"
          data-testid={`prompt-fork-delete-${fork.id}`}
        >
          <Trash2 className="h-3 w-3" aria-hidden="true" />
        </button>
      ) : null}
    </li>
  );
}

import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { BrowserPreview } from "@/components/runs/BrowserPreview";
import {
  fetchRun,
  fetchRunArtifacts,
  fetchRunLogs,
  fetchRunSignedUrl,
  fetchRunSteps,
} from "@/lib/api-client";

export const Route = createFileRoute("/_app/runs_/$runId/replay")({
  component: RunReplayPage,
  staticData: { title: "Run replay" },
});

/**
 * Time-travel run replay (M4-10). Read-only step-through of a finished run:
 * prev/next + a scrubber walk the recorded steps; each step shows its captured
 * screenshot, outcome/timing/error, and the run's persisted log + LLM-message
 * stream up to that point. No live streaming — purely historical playback.
 */
export function RunReplayPage(): React.ReactElement {
  const { runId } = Route.useParams();

  const { data: run } = useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => fetchRun(runId),
  });
  const { data: stepsData } = useQuery({
    queryKey: ["run-steps", runId] as const,
    queryFn: () => fetchRunSteps(runId),
  });
  const { data: artifactsData } = useQuery({
    queryKey: ["run-artifacts", runId] as const,
    queryFn: () => fetchRunArtifacts(runId),
  });
  const { data: logsData } = useQuery({
    queryKey: ["run-logs", runId] as const,
    queryFn: () => fetchRunLogs(runId),
  });

  const steps = useMemo(
    () => [...(stepsData?.items ?? [])].sort((a, b) => a.step_order - b.step_order),
    [stepsData],
  );
  const artifacts = useMemo(() => artifactsData?.items ?? [], [artifactsData]);
  const logs = logsData?.items ?? [];

  const [index, setIndex] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    setIndex(0);
  }, [runId]);

  // Clamp when the step list resolves.
  useEffect(() => {
    if (steps.length > 0 && index > steps.length - 1) setIndex(steps.length - 1);
  }, [steps.length, index]);

  const current = steps[index];

  // Resolve the screenshot for the selected step (kind=SCREENSHOT, same step).
  useEffect(() => {
    let cancelled = false;
    setPreviewUrl(null);
    if (!current) return;
    const shot = artifacts.find((a) => a.run_step_id === current.id && a.kind === "SCREENSHOT");
    if (!shot) return;
    void fetchRunSignedUrl(runId, shot.id).then((res) => {
      if (!cancelled) setPreviewUrl(res.url);
    });
    return () => {
      cancelled = true;
    };
  }, [current, artifacts, runId]);

  // Keyboard scrubbing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
      if (e.key === "ArrowRight") setIndex((i) => Math.min(steps.length - 1, i + 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps.length]);

  return (
    <div className="flex flex-col gap-4 p-4" data-testid="run-replay">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[15px] font-semibold text-fg-1">Run replay</h1>
          <p className="text-[12.5px] text-fg-3">{run?.name ?? runId} · read-only time-travel</p>
        </div>
        <Link
          to="/runs/$runId"
          params={{ runId }}
          className="text-[12.5px] text-fg-3 hover:text-fg-1"
        >
          ← Back to run
        </Link>
      </div>

      {steps.length === 0 ? (
        <p className="text-[13px] text-fg-4" data-testid="run-replay-empty">
          No recorded steps to replay.
        </p>
      ) : (
        <>
          {/* Scrubber */}
          <div className="flex items-center gap-3" data-testid="run-replay-scrubber">
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={index === 0}
              aria-label="Previous step"
              className="flex h-7 w-7 items-center justify-center rounded-md border border-border text-fg-3 disabled:opacity-40 hover:bg-bg-elev-2"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <input
              type="range"
              min={0}
              max={steps.length - 1}
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
              aria-label="Step scrubber"
              className="flex-1 accent-accent"
            />
            <button
              type="button"
              onClick={() => setIndex((i) => Math.min(steps.length - 1, i + 1))}
              disabled={index === steps.length - 1}
              aria-label="Next step"
              className="flex h-7 w-7 items-center justify-center rounded-md border border-border text-fg-3 disabled:opacity-40 hover:bg-bg-elev-2"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
            <span className="font-mono text-[12px] text-fg-4">
              {index + 1} / {steps.length}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <BrowserPreview url={previewUrl} />

            {/* Step metadata */}
            <div className="rounded-md border border-border bg-bg-elev-1 p-3 text-[12.5px]">
              <h2 className="mb-2 text-[13px] font-medium text-fg-1">
                Step {current?.step_order} · {current?.case_public_id}
              </h2>
              <dl className="space-y-1.5">
                <Row label="Outcome" value={current?.outcome ?? "—"} />
                <Row
                  label="Duration"
                  value={current?.duration_ms != null ? `${current.duration_ms} ms` : "—"}
                />
                <Row label="Started" value={current?.started_at ?? "—"} />
                {current?.error_message ? (
                  <div className="pt-1">
                    <dt className="text-fg-4">Error</dt>
                    <dd className="mt-0.5 whitespace-pre-wrap font-mono text-[11.5px] text-red">
                      {current.error_message}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </div>
          </div>

          {/* Log + LLM message stream */}
          <div className="rounded-md border border-border bg-bg-elev-1 p-3">
            <h2 className="mb-2 text-[13px] font-medium text-fg-1">Log &amp; LLM messages</h2>
            <div
              className="max-h-[260px] overflow-auto font-mono text-[11.5px] leading-relaxed"
              data-testid="run-replay-log"
            >
              {logs.length === 0 ? (
                <p className="text-fg-5">No persisted log lines.</p>
              ) : (
                logs.map((line) => (
                  <div key={line.seq} className="flex gap-2">
                    <span className="text-fg-5">{line.level}</span>
                    <span className="flex-1 whitespace-pre-wrap text-fg-3">{line.message}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-fg-4">{label}</dt>
      <dd className="text-fg-1">{value}</dd>
    </div>
  );
}

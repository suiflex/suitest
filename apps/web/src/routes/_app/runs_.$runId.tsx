import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { BrowserPreview } from "@/components/runs/BrowserPreview";
import { LogPane, type LogLine } from "@/components/runs/LogPane";
import { RunSummaryCard } from "@/components/runs/RunSummaryCard";
import { StepTable } from "@/components/runs/StepTable";
import { fetchRun, fetchRunArtifacts, fetchRunSignedUrl, fetchRunSteps } from "@/lib/api-client";
import { useRunStream } from "@/lib/ws-client";

export const Route = createFileRoute("/_app/runs_/$runId")({
  component: RunDetailPage,
  staticData: { title: "Run detail" },
});

export function RunDetailPage(): React.ReactElement {
  const { runId } = Route.useParams();

  const { data: run, refetch: refetchRun } = useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => fetchRun(runId),
    // Belt-and-suspenders with the WS stream: poll while the run is non-terminal
    // so the status badge still resolves if a fast run completes during page
    // load (before the WS subscription lands) or if the socket drops.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const terminal = status === "PASS" || status === "FAIL" || status === "ERROR" || status === "CANCELLED";
      return terminal ? false : 2000;
    },
  });
  const { data: stepsData, refetch: refetchSteps } = useQuery({
    queryKey: ["run-steps", runId] as const,
    queryFn: () => fetchRunSteps(runId),
  });
  const { data: artifactsData, refetch: refetchArtifacts } = useQuery({
    queryKey: ["run-artifacts", runId] as const,
    queryFn: () => fetchRunArtifacts(runId),
  });

  const steps = stepsData?.items ?? [];
  // Memo'd so the dependency array of the screenshot-resolver effect is
  // referentially stable across renders that share the same artifact list.
  const artifacts = useMemo(() => artifactsData?.items ?? [], [artifactsData]);

  const [logs, setLogs] = useState<LogLine[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const autoScrollRef = useRef(true);
  // The latest screenshot artifact id we have already resolved a signed URL
  // for — guards against re-fetching the same blob on every artifact poll.
  const lastResolvedScreenshotId = useRef<string | null>(null);

  // Reset transient state whenever the user navigates between two runs.
  useEffect(() => {
    setLogs([]);
    setPreviewUrl(null);
    autoScrollRef.current = true;
    lastResolvedScreenshotId.current = null;
  }, [runId]);

  useRunStream(runId, (e) => {
    switch (e.event) {
      case "run.step.log":
        setLogs((prev) => [...prev, e.data]);
        break;
      case "run.step.started":
      case "run.step.completed":
        // Refetch the run too: its status + passed/failed counts change as
        // steps land, and the summary card status badge reads from it.
        void refetchRun();
        void refetchSteps();
        break;
      case "run.completed":
        void refetchRun();
        void refetchSteps();
        void refetchArtifacts();
        break;
      case "run.started":
        // Flip QUEUED → RUNNING on the summary card the moment execution begins.
        void refetchRun();
        break;
    }
  });

  // Whenever the artifact list changes, find the newest SCREENSHOT and fetch
  // its signed URL. Skip if we already resolved this artifact.
  useEffect(() => {
    const latest = [...artifacts].reverse().find((a) => a.kind === "SCREENSHOT");
    if (!latest) return;
    if (lastResolvedScreenshotId.current === latest.id) return;
    lastResolvedScreenshotId.current = latest.id;
    let cancelled = false;
    void fetchRunSignedUrl(runId, latest.id).then((signed) => {
      if (cancelled) return;
      setPreviewUrl(signed.url);
    });
    return () => {
      cancelled = true;
    };
  }, [artifacts, runId]);

  return (
    <section className="flex flex-col gap-4" data-testid="run-detail-page">
      <div className="flex justify-end">
        <Link
          to="/runs/$runId/replay"
          params={{ runId }}
          className="rounded-md border border-border bg-bg-elev-1 px-2.5 py-1 text-[12.5px] text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          data-testid="run-replay-link"
        >
          ⏱ Time-travel replay
        </Link>
      </div>
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12">
          <RunSummaryCard run={run} />
        </div>
        <div className="col-span-12 lg:col-span-7">
          <StepTable steps={steps} />
        </div>
        <div className="col-span-12 lg:col-span-5">
          <BrowserPreview url={previewUrl} />
        </div>
        <div className="col-span-12">
          <LogPane logs={logs} autoScrollRef={autoScrollRef} />
        </div>
      </div>
    </section>
  );
}

import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
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

  const { data: run } = useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => fetchRun(runId),
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
        void refetchSteps();
        break;
      case "run.completed":
        void refetchSteps();
        void refetchArtifacts();
        break;
      case "run.started":
        // No-op for now — the run summary is already mounted before this
        // event lands because the user navigated in via the runs list.
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

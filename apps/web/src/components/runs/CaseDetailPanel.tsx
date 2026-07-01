import { useQuery } from "@tanstack/react-query";
import { Camera, Download, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  fetchRunLogs,
  fetchRunSignedUrl,
  fetchTestCaseCode,
  fetchTestCaseDescription,
} from "@/lib/api-client";
import type { components } from "@/lib/api-types";

import { formatDuration, rollupLabel, rollupToBadge, type CaseGroup } from "./case-grouping";
import { StepTable } from "./StepTable";

type ArtifactPublic = components["schemas"]["ArtifactPublic"];

interface CaseDetailPanelProps {
  runId: string;
  group: CaseGroup;
  /** All of the run's artifacts (filtered to this case internally). */
  artifacts: ArtifactPublic[];
}

/**
 * TestSprite-style detail for a single test case within a run. Shows Basics,
 * a Description, a Result summary, the case's Steps (filtered), and a
 * Preview | Code | Logs | Artifacts tab strip. Backend/api cases have no
 * media, so Preview + Artifacts degrade to empty states gracefully.
 */
export function CaseDetailPanel({
  runId,
  group,
  artifacts,
}: CaseDetailPanelProps): React.ReactElement {
  const stepIds = useMemo(() => new Set(group.steps.map((s) => s.id)), [group.steps]);

  // Only the artifacts produced by THIS case's steps.
  const caseArtifacts = useMemo(
    () => artifacts.filter((a) => stepIds.has(a.run_step_id)),
    [artifacts, stepIds],
  );

  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [stepShotUrl, setStepShotUrl] = useState<string | null>(null);
  const lastResolvedVideoId = useRef<string | null>(null);

  // Reset transient preview state when the user switches to another case.
  useEffect(() => {
    setSelectedStepId(null);
    setVideoUrl(null);
    setStepShotUrl(null);
    lastResolvedVideoId.current = null;
  }, [group.caseId]);

  // Resolve the case's VIDEO artifact for the Preview tab (frontend cases only).
  useEffect(() => {
    const video = caseArtifacts.find((a) => a.kind === "VIDEO");
    if (!video) {
      setVideoUrl(null);
      lastResolvedVideoId.current = null;
      return;
    }
    if (lastResolvedVideoId.current === video.id) return;
    lastResolvedVideoId.current = video.id;
    let cancelled = false;
    void fetchRunSignedUrl(runId, video.id).then((signed) => {
      if (!cancelled) setVideoUrl(signed.url);
    });
    return () => {
      cancelled = true;
    };
  }, [caseArtifacts, runId]);

  // Resolve the selected step's SCREENSHOT for the per-step preview.
  useEffect(() => {
    if (selectedStepId === null) {
      setStepShotUrl(null);
      return;
    }
    const shot = caseArtifacts.find(
      (a) => a.kind === "SCREENSHOT" && a.run_step_id === selectedStepId,
    );
    if (!shot) {
      setStepShotUrl(null);
      return;
    }
    let cancelled = false;
    void fetchRunSignedUrl(runId, shot.id).then((signed) => {
      if (!cancelled) setStepShotUrl(signed.url);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedStepId, caseArtifacts, runId]);

  const selectedStepLabel = useMemo(() => {
    const s = group.steps.find((x) => x.id === selectedStepId);
    return s ? `Step ${s.step_order.toString()}` : null;
  }, [group.steps, selectedStepId]);

  const { data: code } = useQuery({
    queryKey: ["case-detail-code", group.caseId] as const,
    queryFn: () => fetchTestCaseCode(group.caseId),
  });
  const { data: description } = useQuery({
    queryKey: ["case-detail-desc", group.caseId] as const,
    queryFn: () => fetchTestCaseDescription(group.caseId),
  });
  const { data: logPage } = useQuery({
    queryKey: ["run-logs", runId] as const,
    queryFn: () => fetchRunLogs(runId),
  });
  const logItems = logPage?.items ?? [];

  const resultSummary =
    group.rollup === "fail" && group.firstFailure
      ? group.firstFailure
      : `${group.passed.toString()}/${group.total.toString()} steps passed`;

  return (
    <div className="flex flex-col gap-4" data-testid="case-detail">
      {/* Basics */}
      <div className="flex flex-col gap-2 border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <StatusBadge status={rollupToBadge(group.rollup)} label={rollupLabel(group.rollup)} />
          <span className="font-mono text-[11px] text-fg-5">{group.casePublicId}</span>
          <span
            className="rounded bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-4"
            data-testid="case-kind-badge"
          >
            {group.kind}
          </span>
          <span className="ml-auto font-mono text-[11px] text-fg-4 tabular-nums">
            {formatDuration(group.durationMs)}
          </span>
        </div>
        <h3
          className="text-[15px] font-semibold leading-tight tracking-[-.01em] text-fg-1"
          data-testid="case-detail-title"
        >
          {group.caseName}
        </h3>
        {description && description.trim().length > 0 ? (
          <p
            className="text-[12px] leading-relaxed text-fg-3"
            data-testid="case-detail-description"
          >
            {description}
          </p>
        ) : null}
        <p className="text-[12px] text-fg-4" data-testid="case-result-summary">
          {resultSummary}
        </p>
      </div>

      {/* Steps */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[10.5px] uppercase tracking-wide text-fg-5">Steps</span>
        <StepTable
          steps={group.steps}
          selectedStepId={selectedStepId}
          onSelectStep={(stepId) => {
            setSelectedStepId((prev) => (prev === stepId ? null : stepId));
          }}
        />
      </div>

      {/* Evidence tabs */}
      <CaseEvidenceTabs
        code={code ?? null}
        videoUrl={videoUrl}
        stepScreenshotUrl={stepShotUrl}
        stepLabel={selectedStepLabel}
        onClearStep={() => {
          setSelectedStepId(null);
        }}
        logs={logItems}
        artifacts={caseArtifacts}
        runId={runId}
      />
    </div>
  );
}

interface CaseEvidenceTabsProps {
  code: string | null;
  videoUrl: string | null;
  stepScreenshotUrl: string | null;
  stepLabel: string | null;
  onClearStep: () => void;
  logs: components["schemas"]["RunLogItem"][];
  artifacts: ArtifactPublic[];
  runId: string;
}

function CaseEvidenceTabs({
  code,
  videoUrl,
  stepScreenshotUrl,
  stepLabel,
  onClearStep,
  logs,
  artifacts,
  runId,
}: CaseEvidenceTabsProps): React.ReactElement {
  const [tab, setTab] = useState("preview");
  const showStep = Boolean(stepScreenshotUrl);

  return (
    <Tabs value={tab} onValueChange={setTab} data-testid="case-evidence-tabs">
      <TabsList variant="line">
        <TabsTrigger value="preview">Preview</TabsTrigger>
        <TabsTrigger value="code">Code</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
        <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
      </TabsList>

      <TabsContent value="preview">
        <div className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-3">
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-fg-4">
            <span className="ml-auto">
              {showStep ? `Preview: ${stepLabel ?? "step"}` : videoUrl ? "video" : "no preview"}
            </span>
            {showStep ? (
              <button
                type="button"
                onClick={onClearStep}
                aria-label="Back to case video"
                data-testid="case-preview-clear-step"
                className="rounded p-0.5 text-fg-4 hover:bg-bg-elev-2 hover:text-fg-1"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            ) : null}
          </div>
          <div className="flex h-[280px] items-center justify-center overflow-hidden rounded-md bg-bg-code text-[12px] text-fg-5">
            {showStep && stepScreenshotUrl ? (
              <img
                src={stepScreenshotUrl}
                alt={stepLabel ? `${stepLabel} screenshot` : "Step screenshot"}
                data-testid="case-preview-step-image"
                className="max-h-full max-w-full object-contain"
              />
            ) : videoUrl ? (
              <video
                src={videoUrl}
                controls
                data-testid="case-preview-video"
                className="max-h-full max-w-full"
              />
            ) : (
              <span className="flex items-center gap-2" data-testid="case-preview-placeholder">
                <Camera className="h-4 w-4" aria-hidden="true" />
                No preview for this case
              </span>
            )}
          </div>
        </div>
      </TabsContent>

      <TabsContent value="code">
        <pre
          className="h-[280px] overflow-auto rounded-md border border-border bg-bg-code p-3 font-mono text-[11.5px] leading-relaxed text-fg-3"
          data-testid="case-code"
        >
          {code ?? "No generated source."}
        </pre>
      </TabsContent>

      <TabsContent value="logs">
        {logs.length === 0 ? (
          <div className="text-[12px] text-fg-4" data-testid="case-logs-empty">
            No logs.
          </div>
        ) : (
          <pre
            data-testid="case-logs"
            className="max-h-[320px] overflow-auto rounded-md border border-border bg-bg-code p-[14px] font-mono text-[11.5px] leading-relaxed text-fg-1"
          >
            {logs.map((item) => (
              <div key={item.seq}>{item.message}</div>
            ))}
          </pre>
        )}
      </TabsContent>

      <TabsContent value="artifacts">
        {artifacts.length === 0 ? (
          <div className="text-[12px] text-fg-4" data-testid="case-artifacts-empty">
            No artifacts captured for this case.
          </div>
        ) : (
          <ul className="flex flex-col gap-1.5" data-testid="case-artifacts">
            {artifacts.map((a) => (
              <CaseArtifactRow key={a.id} artifact={a} runId={runId} />
            ))}
          </ul>
        )}
      </TabsContent>
    </Tabs>
  );
}

function CaseArtifactRow({
  artifact,
  runId,
}: {
  artifact: ArtifactPublic;
  runId: string;
}): React.ReactElement {
  const [url, setUrl] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const handleView = (): void => {
    if (url) {
      setOpen((v) => !v);
      return;
    }
    void fetchRunSignedUrl(runId, artifact.id).then((signed) => {
      setUrl(signed.url);
      setOpen(true);
    });
  };

  const isViewable = artifact.kind === "SCREENSHOT" || artifact.kind === "VIDEO";

  return (
    <li
      className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-2.5"
      data-testid="case-artifact"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[12.5px]">
          <span className="font-mono text-[11px] text-fg-3">{artifact.kind}</span>
          <span className="text-fg-1">{artifact.mime_type}</span>
        </div>
        {isViewable ? (
          <button
            type="button"
            onClick={handleView}
            data-testid="case-artifact-view"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2 py-1 text-[12px] text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            {open ? "Hide" : "View"}
          </button>
        ) : null}
      </div>
      {open && url ? (
        <div className="overflow-hidden rounded-md bg-bg-code">
          {artifact.kind === "VIDEO" ? (
            <video src={url} controls className="max-h-[280px] w-full" />
          ) : (
            <img
              src={url}
              alt={`${artifact.kind} artifact`}
              className="max-h-[280px] w-full object-contain"
            />
          )}
        </div>
      ) : null}
    </li>
  );
}

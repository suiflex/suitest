import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/shared/EmptyState";
import { fetchRunSignedUrl } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

import {
  diffImage,
  diffPctColor,
  pixelDiffPct,
  type DiffMode,
} from "./screenshot-diff";

type ArtifactPublic = components["schemas"]["ArtifactPublic"];

interface ScreenshotDiffViewerProps {
  /** Run id (or public id) — used to resolve presigned artifact URLs. */
  runId: string;
  /** Artifacts already filtered to SCREENSHOT kind by the parent. */
  artifacts: ArtifactPublic[];
}

type ViewMode = "side-by-side" | "overlay" | "diff";

/**
 * M12-1 — screenshot diff viewer (pixel mode, deterministic / ZERO tier).
 * Compares any two SCREENSHOT artifacts captured in the same run: loads both
 * via the presigned-URL API, draws them to a canvas, and reports the pixel-diff
 * percentage plus a red-overlay visualization. Perceptual mode is scaffolded
 * as a disabled toggle — it lands in M12-2 behind an LLM gate.
 */
export function ScreenshotDiffViewer({
  runId,
  artifacts,
}: ScreenshotDiffViewerProps): React.ReactElement {
  // Two pickers default to the first two screenshots.
  const [aId, setAId] = useState<string | null>(null);
  const [bId, setBId] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>("side-by-side");
  const [mode, setMode] = useState<DiffMode>("pixel");

  // Reset picks when the artifact set changes (e.g. switching test case).
  useEffect(() => {
    const first = artifacts[0]?.id ?? null;
    const second = artifacts[1]?.id ?? first;
    setAId(first);
    setBId(second);
  }, [artifacts]);

  if (artifacts.length < 2) {
    return (
      <div data-testid="screenshot-diff-empty">
        <EmptyState
          icon={GitCompareArrows}
          title="Need at least 2 screenshots to compare"
          subtitle="This test case captured fewer than two screenshots, so there is nothing to diff."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="screenshot-diff-viewer">
      {/* Controls: pickers + mode + view */}
      <div className="flex flex-wrap items-end gap-3">
        <Picker
          label="A"
          artifacts={artifacts}
          value={aId}
          onChange={setAId}
          testId="diff-pick-a"
        />
        <Picker
          label="B"
          artifacts={artifacts}
          value={bId}
          onChange={setBId}
          testId="diff-pick-b"
        />
        <ModeToggle mode={mode} onModeChange={setMode} />
        <ViewToggle view={view} onViewChange={setView} />
      </div>

      <DiffCanvas
        runId={runId}
        aId={aId}
        bId={bId}
        view={view}
        // mode is always "pixel" today; perceptual is a disabled stub.
        computeMode="pixel"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Picker({
  label,
  artifacts,
  value,
  onChange,
  testId,
}: {
  label: string;
  artifacts: ArtifactPublic[];
  value: string | null;
  onChange: (id: string) => void;
  testId: string;
}): React.ReactElement {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10.5px] uppercase tracking-wide text-fg-5">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testId}
        className="rounded-md border border-border bg-bg-elev-1 px-2 py-1 font-mono text-[12px] text-fg-1 focus:border-accent focus:outline-none"
      >
        {artifacts.map((a, i) => (
          <option key={a.id} value={a.id}>
            #{(i + 1).toString().padStart(2, "0")} · {a.id}
          </option>
        ))}
      </select>
    </label>
  );
}

function ModeToggle({
  mode,
  onModeChange,
}: {
  mode: DiffMode;
  onModeChange: (m: DiffMode) => void;
}): React.ReactElement {
  return (
    <div
      className="flex rounded-md border border-border bg-bg-elev-1 p-0.5"
      role="group"
      aria-label="Diff mode"
      data-testid="diff-mode"
    >
      <ModeButton
        active={mode === "pixel"}
        disabled={false}
        onClick={() => onModeChange("pixel")}
        testId="diff-mode-pixel"
      >
        Pixel
      </ModeButton>
      <ModeButton
        active={mode === "perceptual"}
        disabled
        onClick={() => undefined}
        testId="diff-mode-perceptual"
        title="Perceptual mode arrives with the vision LLM (M12-2)"
      >
        Perceptual
      </ModeButton>
    </div>
  );
}

function ModeButton({
  active,
  disabled,
  onClick,
  children,
  testId,
  title,
}: {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId: string;
  title?: string;
}): React.ReactElement {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={title}
      data-testid={testId}
      className={cn(
        "rounded px-2 py-0.5 text-[12px]",
        active ? "bg-bg-elev-2 text-fg-1" : "text-fg-4 hover:text-fg-1",
        disabled && "cursor-not-allowed opacity-40 hover:text-fg-4",
      )}
    >
      {children}
    </button>
  );
}

function ViewToggle({
  view,
  onViewChange,
}: {
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
}): React.ReactElement {
  const views: ViewMode[] = ["side-by-side", "overlay", "diff"];
  return (
    <div
      className="flex rounded-md border border-border bg-bg-elev-1 p-0.5"
      role="group"
      aria-label="View mode"
      data-testid="diff-view"
    >
      {views.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onViewChange(v)}
          data-testid={`diff-view-${v}`}
          className={cn(
            "rounded px-2 py-0.5 text-[12px]",
            view === v ? "bg-bg-elev-2 text-fg-1" : "text-fg-4 hover:text-fg-1",
          )}
        >
          {v === "side-by-side" ? "Side" : v === "overlay" ? "Overlay" : "Diff"}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------

function DiffCanvas({
  runId,
  aId,
  bId,
  view,
  computeMode,
}: {
  runId: string;
  aId: string | null;
  bId: string | null;
  view: ViewMode;
  computeMode: DiffMode;
}): React.ReactElement {
  const aUrl = useSignedUrl(runId, aId);
  const bUrl = useSignedUrl(runId, bId);

  // Load both images into HTMLImageElement for canvas drawing.
  const aImg = useImage(aUrl);
  const bImg = useImage(bUrl);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Redraw whenever images or view change.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) return;
    const ctx = canvas.getContext("2d");
    if (ctx === null) return;

    // Clear previous frame + state.
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setPct(null);
    setNotice(null);

    if (aImg.status !== "loaded" || bImg.status !== "loaded") return;
    const imgA = aImg.image;
    const imgB = bImg.image;
    if (imgA === null || imgB === null) return;

    // Comparison canvas is sized to the smaller dimensions.
    const w = Math.min(imgA.naturalWidth, imgB.naturalWidth);
    const h = Math.min(imgA.naturalHeight, imgB.naturalHeight);
    if (w === 0 || h === 0) return;
    canvas.width = w;
    canvas.height = h;

    if (view === "side-by-side") {
      // Side-by-side: draw A left, B right at half width each.
      canvas.width = w * 2;
      ctx.drawImage(imgA, 0, 0, w, h);
      ctx.drawImage(imgB, w, 0, w, h);
      return;
    }

    if (view === "overlay") {
      // B drawn at 50% opacity over A — the classic flicker compare.
      ctx.drawImage(imgA, 0, 0, w, h);
      ctx.globalAlpha = 0.5;
      ctx.drawImage(imgB, 0, 0, w, h);
      ctx.globalAlpha = 1;
      return;
    }

    // view === "diff" — compute the pixel-diff overlay.
    if (computeMode !== "pixel") {
      setNotice("Perceptual mode arrives with the vision LLM (M12-2).");
      ctx.drawImage(imgA, 0, 0, w, h);
      return;
    }
    ctx.drawImage(imgA, 0, 0, w, h);
    const dataA = ctx.getImageData(0, 0, w, h);
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(imgB, 0, 0, w, h);
    const dataB = ctx.getImageData(0, 0, w, h);
    const diff = diffImage(dataA, dataB);
    ctx.putImageData(diff, 0, 0);
    setPct(pixelDiffPct(dataA, dataB));
  }, [aImg, bImg, view, computeMode]);

  const loading = aImg.status === "loading" || bImg.status === "loading";
  const error = aImg.status === "error" || bImg.status === "error";

  return (
    <div className="flex flex-col gap-2" data-testid="diff-canvas-wrap">
      <div className="flex items-center gap-2 font-mono text-[11px] text-fg-4">
        {pct !== null ? (
          <span
            className={cn("font-semibold", diffPctColor(pct))}
            data-testid="diff-pct"
          >
            {pct.toFixed(1)}% pixel diff
          </span>
        ) : (
          <span data-testid="diff-pct-pending">—</span>
        )}
        {notice ? <span className="text-amber">{notice}</span> : null}
      </div>
      <div className="flex min-h-[280px] items-center justify-center overflow-hidden rounded-md border border-border bg-bg-code text-[12px] text-fg-5">
        {error ? (
          <span data-testid="diff-canvas-error">Could not load one or both screenshots.</span>
        ) : loading ? (
          <span data-testid="diff-canvas-loading">Loading screenshots…</span>
        ) : (
          <canvas
            ref={canvasRef}
            data-testid="diff-canvas"
            className="max-h-[420px] max-w-full object-contain"
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

/** Resolve a presigned URL for an artifact id, cached per (runId, id). */
function useSignedUrl(runId: string, artifactId: string | null): string | null {
  const { data } = useQuery({
    queryKey: ["artifact-signed", runId, artifactId] as const,
    queryFn: () => fetchRunSignedUrl(runId, artifactId as string),
    enabled: artifactId !== null,
  });
  return data?.url ?? null;
}

type ImageState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; image: HTMLImageElement | null }
  | { status: "error" };

/** Load a URL into an HTMLImageElement, tracking load/error for the canvas. */
function useImage(url: string | null): ImageState {
  const [state, setState] = useState<ImageState>({ status: "idle" });

  useEffect(() => {
    if (url === null) {
      setState({ status: "idle" });
      return;
    }
    setState({ status: "loading" });
    const img = new Image();
    img.onload = () => setState({ status: "loaded", image: img });
    img.onerror = () => setState({ status: "error" });
    img.src = url;
    return () => {
      img.onload = null;
      img.onerror = null;
    };
  }, [url]);

  return state;
}

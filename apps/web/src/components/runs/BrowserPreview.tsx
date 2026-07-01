import { Camera, X } from "lucide-react";
import { useState } from "react";

interface BrowserPreviewProps {
  url: string | null;
  /** Presigned URL of the run's VIDEO artifact, if any (Phase 2). */
  videoUrl?: string | null;
  /** Generated test source for the Code tab (Phase 2 lifecycle ingest). */
  code?: string | null;
  /** Presigned screenshot URL for the step the user clicked (per-step preview). */
  stepScreenshotUrl?: string | null;
  /** Label of the selected step, e.g. "Step 3". */
  stepLabel?: string | null;
  /** Clear the selected step and return to the run video. */
  onClearStep?: () => void;
}

type Tab = "preview" | "code";

/**
 * Run preview pane. Two tabs (TestSprite-style):
 *  - **Preview**: plays the run VIDEO when present, else the latest SCREENSHOT.
 *  - **Code**: the persisted generated test source (read-only).
 * The parent route resolves the presigned URLs + code and feeds them in.
 */
export function BrowserPreview({
  url,
  videoUrl,
  code,
  stepScreenshotUrl,
  stepLabel,
  onClearStep,
}: BrowserPreviewProps): React.ReactElement {
  const [tab, setTab] = useState<Tab>("preview");
  const hasCode = Boolean(code);
  const showStep = Boolean(stepScreenshotUrl);

  return (
    <div
      className="flex flex-col rounded-md border border-border bg-bg-elev-1 p-3"
      data-testid="browser-preview"
    >
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <button
          type="button"
          onClick={() => setTab("preview")}
          className={`rounded-md px-2 py-0.5 text-[12px] ${
            tab === "preview" ? "bg-bg-elev-2 text-fg-1" : "text-fg-4 hover:text-fg-1"
          }`}
          data-testid="preview-tab"
        >
          Preview
        </button>
        <button
          type="button"
          onClick={() => setTab("code")}
          disabled={!hasCode}
          className={`rounded-md px-2 py-0.5 text-[12px] ${
            tab === "code" ? "bg-bg-elev-2 text-fg-1" : "text-fg-4 hover:text-fg-1"
          } disabled:opacity-40`}
          data-testid="code-tab"
        >
          Code
        </button>
        <span className="ml-auto flex items-center gap-1.5 truncate text-right font-mono text-[11px] text-fg-4">
          {tab === "preview"
            ? showStep
              ? `Preview: ${stepLabel ?? "step"}`
              : videoUrl
                ? "video"
                : "screenshot"
            : "test source"}
          {tab === "preview" && showStep && onClearStep ? (
            <button
              type="button"
              onClick={onClearStep}
              aria-label="Back to run video"
              data-testid="preview-clear-step"
              className="rounded p-0.5 text-fg-4 hover:bg-bg-elev-2 hover:text-fg-1"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          ) : null}
        </span>
      </div>

      {tab === "preview" ? (
        <div className="mt-3 flex h-[280px] items-center justify-center overflow-hidden rounded-md bg-bg-code text-[12px] text-fg-5">
          {showStep && stepScreenshotUrl ? (
            <img
              src={stepScreenshotUrl}
              alt={stepLabel ? `${stepLabel} screenshot` : "Step screenshot"}
              data-testid="browser-preview-step-image"
              className="max-h-full max-w-full object-contain"
            />
          ) : videoUrl ? (
            <video
              src={videoUrl}
              controls
              data-testid="browser-preview-video"
              className="max-h-full max-w-full"
            />
          ) : url ? (
            <img
              src={url}
              alt="Latest run screenshot"
              data-testid="browser-preview-image"
              className="max-h-full max-w-full object-contain"
            />
          ) : (
            <span className="flex items-center gap-2" data-testid="browser-preview-placeholder">
              <Camera className="h-4 w-4" aria-hidden="true" />
              Preview
            </span>
          )}
        </div>
      ) : (
        <pre
          className="mt-3 h-[280px] overflow-auto rounded-md bg-bg-code p-3 font-mono text-[11.5px] leading-relaxed text-fg-3"
          data-testid="browser-preview-code"
        >
          {code ?? "No generated source."}
        </pre>
      )}
    </div>
  );
}

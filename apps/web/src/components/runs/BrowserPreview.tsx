import { Camera } from "lucide-react";

interface BrowserPreviewProps {
  url: string | null;
}

/**
 * Renders the latest SCREENSHOT artifact as a fake browser chrome. When no
 * screenshot is available we show a neutral placeholder — the parent route
 * is responsible for re-fetching the presigned URL whenever a new
 * screenshot artifact lands.
 */
export function BrowserPreview({ url }: BrowserPreviewProps): React.ReactElement {
  return (
    <div
      className="flex flex-col rounded-md border border-border bg-bg-elev-1 p-3"
      data-testid="browser-preview"
    >
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <span className="inline-block h-2 w-2 rounded-full bg-red" aria-hidden="true" />
        <span className="inline-block h-2 w-2 rounded-full bg-amber" aria-hidden="true" />
        <span className="inline-block h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
        <span className="ml-3 flex-1 truncate rounded-md bg-bg-elev-2 px-2 py-0.5 font-mono text-[11px] text-fg-4">
          screenshot
        </span>
      </div>
      <div className="mt-3 flex h-[280px] items-center justify-center overflow-hidden rounded-md bg-[#060606] text-[12px] text-fg-5">
        {url ? (
          <img
            src={url}
            alt="Latest run screenshot"
            data-testid="browser-preview-image"
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <span className="flex items-center gap-2" data-testid="browser-preview-placeholder">
            <Camera className="h-4 w-4" aria-hidden="true" />
            Screenshot preview
          </span>
        )}
      </div>
    </div>
  );
}

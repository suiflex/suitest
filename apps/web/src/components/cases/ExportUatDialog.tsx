import { FileDown, FileText, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { exportUatDocument } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type Locale = "id" | "en";

export interface ExportUatDialogProps {
  projectId: string;
  /** Internal case IDs to include in the document. */
  selectedIds: string[];
  /** Seeds the document title field. */
  projectName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const LOCALES: { value: Locale; label: string; sub: string }[] = [
  { value: "id", label: "ID", sub: "Bahasa Indonesia" },
  { value: "en", label: "EN", sub: "English" },
];

/**
 * Compose a branded UAT acceptance document from a hand-picked set of test
 * cases. The dialog renders a small "document manifest" — a title, a language
 * choice, and a live count of the cases that will be bound into the PDF — then
 * streams the rendered file straight to a browser download.
 *
 * ZERO-tier: pure server-side document rendering, no LLM, no capability gate.
 */
export function ExportUatDialog({
  projectId,
  selectedIds,
  projectName,
  open,
  onOpenChange,
}: ExportUatDialogProps): React.ReactElement {
  const [title, setTitle] = useState(projectName);
  const [locale, setLocale] = useState<Locale>("id");
  const [busy, setBusy] = useState(false);

  const count = selectedIds.length;
  const empty = count === 0;
  const trimmed = title.trim();

  // Re-seed the title each time the dialog opens so it always reflects the
  // current project (the component is rendered persistently by the caller).
  useEffect(() => {
    if (open) {
      setTitle(projectName);
      setLocale("id");
    }
  }, [open, projectName]);

  const handleExport = async (): Promise<void> => {
    if (empty || busy) return;
    setBusy(true);
    try {
      const blob = await exportUatDocument(projectId, {
        case_ids: selectedIds,
        title: trimmed || projectName,
        locale,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `uat-${projectId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`UAT document exported — ${count} case${count === 1 ? "" : "s"}.`);
      onOpenChange(false);
    } catch {
      toast.error("Couldn't export the UAT document. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="export-uat-dialog" className="gap-0 overflow-hidden p-0">
        {/* Accent top-rule — the "document seal" cue */}
        <div className="h-[3px] w-full bg-gradient-to-r from-accent/70 via-accent to-accent/40" />

        <form
          className="flex flex-col gap-5 p-6"
          onSubmit={(e) => {
            e.preventDefault();
            void handleExport();
          }}
        >
          <DialogHeader>
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-bg-elev-2 text-accent"
              >
                <FileText className="h-4 w-4" />
              </span>
              <DialogTitle className="text-[16px]">Export UAT document</DialogTitle>
            </div>
            <DialogDescription>
              Bind the selected cases into a branded, sign-off–ready acceptance PDF.
            </DialogDescription>
          </DialogHeader>

          {/* Selected-case manifest — mono count chip over a hairline surface */}
          <div
            data-testid="export-uat-summary"
            className={cn(
              "flex items-center justify-between rounded-lg border border-border bg-bg-elev-1 px-3.5 py-3",
              empty && "border-amber/40",
            )}
          >
            <span className="text-[12px] text-fg-3">
              {empty
                ? "No cases selected — pick at least one to export."
                : "Cases in this document"}
            </span>
            <span
              className={cn(
                "shrink-0 rounded-md px-2 py-0.5 font-mono text-[13px] tabular-nums",
                empty ? "bg-bg-elev-2 text-fg-5" : "bg-accent/10 text-accent",
              )}
            >
              {count}
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="export-uat-title">Document title</Label>
            <Input
              id="export-uat-title"
              data-testid="export-uat-title"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
              }}
              placeholder={projectName}
              autoComplete="off"
            />
          </div>

          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1.5 text-sm font-medium leading-none text-fg-1">Language</legend>
            <div
              role="radiogroup"
              aria-label="Document language"
              data-testid="export-uat-locale"
              className="grid grid-cols-2 gap-2"
            >
              {LOCALES.map((opt) => {
                const active = locale === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    data-testid={`export-uat-locale-${opt.value}`}
                    onClick={() => {
                      setLocale(opt.value);
                    }}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                      active
                        ? "border-accent/50 bg-accent/[0.07]"
                        : "border-border bg-bg-elev-1 hover:bg-bg-elev-2",
                    )}
                  >
                    <span
                      className={cn(
                        "font-mono text-[13px] font-semibold",
                        active ? "text-accent" : "text-fg-3",
                      )}
                    >
                      {opt.label}
                    </span>
                    <span className="text-[11.5px] text-fg-4">{opt.sub}</span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              data-testid="export-uat-submit"
              disabled={empty || busy}
            >
              {busy ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Exporting…
                </>
              ) : (
                <>
                  <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
                  Export PDF
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

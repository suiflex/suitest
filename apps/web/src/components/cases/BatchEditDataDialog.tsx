import { ArrowRight, Check, Database, Edit3, KeyRound, Loader2, Sparkles } from "lucide-react";
import * as React from "react";
import { useState } from "react";
import { toast } from "sonner";

import { VariableBadge } from "@/components/shared/VariableBadge";
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
import { useBulkUpdate } from "@/hooks/use-test-cases";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

type Case = components["schemas"]["TestCaseListItem"];

export interface BatchEditDataDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedIds: string[];
  cases?: Case[];
  onSuccess?: () => void;
}

type EditMode = "replace" | "bind";
type TargetFieldReplace = "all" | "text" | "url";
type TargetFieldBind = "password" | "username" | "url" | "text";

export function BatchEditDataDialog({
  open,
  onOpenChange,
  selectedIds,
  cases = [],
  onSuccess,
}: BatchEditDataDialogProps): React.ReactElement {
  const [mode, setMode] = useState<EditMode>("replace");
  const [findText, setFindText] = useState("");
  const [replaceWith, setReplaceWith] = useState("");
  const [targetFieldReplace, setTargetFieldReplace] = useState<TargetFieldReplace>("all");
  const [variableKey, setVariableKey] = useState("");
  const [targetFieldBind, setTargetFieldBind] = useState<TargetFieldBind>("password");

  const bulkUpdate = useBulkUpdate();

  const selectedCases = cases.filter((c) => selectedIds.includes(c.id));
  const count = selectedIds.length;

  const handleApply = (): void => {
    if (mode === "replace") {
      const trimmedFind = findText.trim();
      if (!trimmedFind) {
        toast.error("Find text cannot be empty.");
        return;
      }

      bulkUpdate.mutate(
        {
          action: "batch_replace_data",
          ids: selectedIds,
          payload: {
            findText: trimmedFind,
            replaceWith: replaceWith.trim(),
            targetField: targetFieldReplace,
          },
        },
        {
          onSuccess: (res) => {
            toast.success(`Batch updated test data across ${res.updated} cases.`);
            onOpenChange(false);
            onSuccess?.();
          },
          onError: (err) => {
            toast.error(err?.message || "Failed to batch replace data.");
          },
        },
      );
    } else {
      const trimmedVar = variableKey.trim().replace(/^\{\{|\}\}$/g, "");
      if (!trimmedVar) {
        toast.error("Variable key cannot be empty.");
        return;
      }

      bulkUpdate.mutate(
        {
          action: "batch_bind_variable",
          ids: selectedIds,
          payload: {
            variableKey: trimmedVar,
            targetField: targetFieldBind,
          },
        },
        {
          onSuccess: (res) => {
            toast.success(`Bound variable {{${trimmedVar}}} across ${res.updated} cases.`);
            onOpenChange(false);
            onSuccess?.();
          },
          onError: (err) => {
            toast.error(err?.message || "Failed to bind variable.");
          },
        },
      );
    }
  };

  const isApplyDisabled =
    count === 0 ||
    bulkUpdate.isPending ||
    (mode === "replace" && !findText.trim()) ||
    (mode === "bind" && !variableKey.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="batch-edit-data-dialog" className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-5 w-5 text-accent" />
            Batch Edit Test Data
          </DialogTitle>
          <DialogDescription>
            Update credentials, URLs, and shared variable placeholders across {count} selected test{" "}
            {count === 1 ? "case" : "cases"}.
          </DialogDescription>
        </DialogHeader>

        {/* Mode Selector */}
        <div className="flex rounded-lg border border-border bg-bg-elev-1 p-1">
          <button
            type="button"
            data-testid="tab-replace"
            onClick={() => setMode("replace")}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors",
              mode === "replace"
                ? "bg-bg-elev-2 text-fg-1 shadow-sm"
                : "text-fg-3 hover:text-fg-1",
            )}
          >
            <Edit3 className="h-3.5 w-3.5" />
            Find & Replace Text
          </button>
          <button
            type="button"
            data-testid="tab-bind"
            onClick={() => setMode("bind")}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors",
              mode === "bind"
                ? "bg-bg-elev-2 text-fg-1 shadow-sm"
                : "text-fg-3 hover:text-fg-1",
            )}
          >
            <KeyRound className="h-3.5 w-3.5" />
            Bind Shared Variable
          </button>
        </div>

        {/* Mode Content */}
        <div className="space-y-4 py-2">
          {mode === "replace" ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="find-text" className="text-xs text-fg-2">
                    Find Text / Pattern
                  </Label>
                  <Input
                    id="find-text"
                    data-testid="find-text-input"
                    value={findText}
                    onChange={(e) => setFindText(e.target.value)}
                    placeholder="e.g. https://staging.dev"
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="replace-with" className="text-xs text-fg-2">
                    Replace With
                  </Label>
                  <Input
                    id="replace-with"
                    data-testid="replace-with-input"
                    value={replaceWith}
                    onChange={(e) => setReplaceWith(e.target.value)}
                    placeholder="e.g. {{BASE_URL}}"
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="target-field-replace" className="text-xs text-fg-2">
                  Target Field Scope
                </Label>
                <select
                  id="target-field-replace"
                  data-testid="target-field-select"
                  value={targetFieldReplace}
                  onChange={(e) => setTargetFieldReplace(e.target.value as TargetFieldReplace)}
                  className="h-8 w-full rounded-md border border-border bg-bg-elev-1 px-2 text-xs text-fg-2 focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="all">All Fields (Steps, Expected Results, Arguments)</option>
                  <option value="text">Action Text & Expected Results Only</option>
                  <option value="url">URLs & Navigation Targets Only</option>
                </select>
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="target-field-bind" className="text-xs text-fg-2">
                    Target Input Type
                  </Label>
                  <select
                    id="target-field-bind"
                    data-testid="target-field-bind-select"
                    value={targetFieldBind}
                    onChange={(e) => setTargetFieldBind(e.target.value as TargetFieldBind)}
                    className="h-8 w-full rounded-md border border-border bg-bg-elev-1 px-2 text-xs text-fg-2 focus:outline-none focus:ring-1 focus:ring-accent"
                  >
                    <option value="password">Password Input Fields</option>
                    <option value="username">Username / Email Fields</option>
                    <option value="url">Navigation URLs</option>
                    <option value="text">All Action Text</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="variable-key" className="text-xs text-fg-2">
                    Variable Key
                  </Label>
                  <Input
                    id="variable-key"
                    data-testid="variable-key-input"
                    value={variableKey}
                    onChange={(e) => setVariableKey(e.target.value)}
                    placeholder="e.g. ADMIN_PASSWORD"
                    className="h-8 text-xs font-mono uppercase"
                  />
                </div>
              </div>

              {variableKey.trim() && (
                <div className="flex items-center gap-2 rounded border border-border/60 bg-bg-elev-1 px-3 py-2 text-xs text-fg-3">
                  <Sparkles className="h-4 w-4 text-accent" />
                  <span>Placeholder Preview:</span>
                  <VariableBadge
                    name={variableKey.trim().replace(/^\{\{|\}\}$/g, "")}
                    isSecret={targetFieldBind === "password"}
                    scope="workspace"
                  />
                </div>
              )}
            </>
          )}

          {/* Live Preview Diff Box */}
          <div
            data-testid="preview-diff-container"
            className="rounded-lg border border-border bg-bg-elev-1 p-3 space-y-2 text-xs"
          >
            <div className="flex items-center justify-between text-fg-3">
              <span className="font-semibold text-fg-2">Affected Test Cases ({count}):</span>
              {mode === "replace" && findText.trim() && (
                <div className="flex items-center gap-1.5 font-mono text-[11px]">
                  <span className="rounded bg-red/10 px-1.5 py-0.5 text-red">
                    &quot;{findText}&quot;
                  </span>
                  <ArrowRight className="h-3 w-3 text-fg-4" />
                  <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-400">
                    &quot;{replaceWith || '""'}&quot;
                  </span>
                </div>
              )}
            </div>

            <div className="max-h-28 overflow-y-auto space-y-1.5 pr-1">
              {selectedCases.length > 0 ? (
                selectedCases.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between rounded border border-border/40 bg-bg px-2 py-1 text-fg-3"
                  >
                    <span className="truncate max-w-[280px] font-medium text-fg-2">
                      {c.title || c.name}
                    </span>
                    <span className="font-mono text-[11px] text-fg-4">{c.public_id}</span>
                  </div>
                ))
              ) : (
                <div className="text-center py-2 text-fg-4 italic">
                  {count} cases selected by ID
                </div>
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="ghost"
            data-testid="cancel-batch-btn"
            disabled={bulkUpdate.isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            data-testid="apply-batch-btn"
            disabled={isApplyDisabled}
            onClick={handleApply}
          >
            {bulkUpdate.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Updating...
              </>
            ) : (
              <>
                <Check className="mr-1.5 h-4 w-4" />
                Apply to {count} {count === 1 ? "Case" : "Cases"}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

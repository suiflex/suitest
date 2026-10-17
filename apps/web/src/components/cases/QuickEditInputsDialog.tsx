import * as React from "react";
import { useState, useEffect, useRef, useMemo } from "react";
import {
  ArrowRight,
  Database,
  Eye,
  EyeOff,
  FileUp,
  FolderInput,
  KeyRound,
  Loader2,
  Paperclip,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { VariableBadge } from "@/components/shared/VariableBadge";
import { api } from "@/lib/api-client";
import { useTestCase } from "@/hooks/use-test-cases";
import { useResolvedVariables, type ResolvedVariableItem } from "@/hooks/use-variables";
import type { DraftStep } from "@/components/cases/StepEditor";
import {
  detectInputSteps,
  applyStepInputUpdate,
  type DetectedInputType,
} from "@/lib/step-input-detector";
import { cn } from "@/lib/utils";

export interface QuickEditInputsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseId: string;
  caseName?: string | undefined;
  suiteId?: string | null | undefined;
  datasetSchema?: string[] | undefined;
  datasetRows?: Array<{ id?: string; name?: string; enabled?: boolean; values?: Record<string, unknown> }> | undefined;
  steps?: DraftStep[] | undefined;
  onStepsUpdated?: ((steps: DraftStep[]) => void) | undefined;
  canWrite?: boolean | undefined;
}

interface AvailableVar {
  key: string;
  value?: string | null;
  scope: "dataset" | "suite" | "workspace" | "env" | "unbound";
  isSecret: boolean;
  description?: string | null;
  allRowValues?: Array<{ rowName: string; value: string }> | undefined;
}

function isSecretKey(key: string): boolean {
  const lower = key.toLowerCase();
  return (
    lower.includes("pass") ||
    lower.includes("secret") ||
    lower.includes("token") ||
    lower.includes("apikey") ||
    lower.includes("api_key") ||
    lower.includes("auth") ||
    lower.includes("pwd")
  );
}

function getTypeBadge(type: DetectedInputType) {
  switch (type) {
    case "password":
      return { label: "Password", color: "bg-red/10 text-red border-red/20" };
    case "upload":
      return { label: "Upload", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" };
    case "select":
      return { label: "Select", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" };
    case "url":
      return { label: "URL", color: "bg-sky-500/10 text-sky-400 border-sky-500/20" };
    default:
      return { label: "Text Input", color: "bg-fg-4/10 text-fg-3 border-border" };
  }
}

interface VariablePickerPopoverProps {
  stepId: string;
  onSelectVariable: (varKey: string) => void;
  availableVariables: AvailableVar[];
  disabled?: boolean;
}

function VariablePickerPopover({
  stepId,
  onSelectVariable,
  availableVariables,
  disabled = false,
}: VariablePickerPopoverProps) {
  const [open, setOpen] = useState(false);
  const [customKey, setCustomKey] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredVars = useMemo(() => {
    const q = searchQuery.trim();
    if (!q) return availableVariables;
    const regex = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
    return availableVariables.filter((v) => regex.test(`${v.key} ${v.value ?? ""}`));
  }, [availableVariables, searchQuery]);

  const handleApplyCustom = () => {
    const clean = customKey.trim().replace(/^\{\{|\}\}$/g, "");
    if (!clean) return;
    onSelectVariable(clean);
    setCustomKey("");
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="xs"
          variant="outline"
          title="Pick or bind as variable {{variable_name}}"
          data-testid={`bind-var-btn-${stepId}`}
          disabled={disabled}
          className="h-8 px-2.5 font-mono text-[11px] text-purple-400 hover:text-purple-300 hover:bg-purple-500/10 border-border bg-bg-elev-2 shrink-0 gap-1"
        >
          <Sparkles className="h-3 w-3 text-purple-400" />
          {"{{x}}"}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-80 p-3 bg-bg-elev-2 border-border shadow-xl space-y-3 z-50 text-fg-1"
      >
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-fg-1">
            <KeyRound className="h-3.5 w-3.5 text-purple-400" />
            Insert Variable
          </div>
          <span className="text-[10.5px] text-fg-4 font-mono">
            {availableVariables.length} available
          </span>
        </div>

        {/* Custom Variable Creator */}
        <div className="flex items-center gap-1.5">
          <Input
            value={customKey}
            onChange={(e) => setCustomKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleApplyCustom();
              }
            }}
            placeholder="Custom variable key..."
            data-testid={`custom-var-input-${stepId}`}
            className="h-7 text-xs bg-bg-elev-3 border-border font-mono placeholder:font-sans"
          />
          <Button
            type="button"
            size="xs"
            onClick={handleApplyCustom}
            disabled={!customKey.trim()}
            data-testid={`custom-var-apply-btn-${stepId}`}
            className="h-7 px-2 text-xs"
          >
            Bind
          </Button>
        </div>

        {/* Search existing */}
        {availableVariables.length > 3 ? (
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search variables..."
            className="h-6 text-[11px] bg-bg-elev-1 border-border/80"
          />
        ) : null}

        {/* Existing Variables List */}
        <div className="max-h-48 overflow-y-auto space-y-1.5 pt-1" data-testid={`variables-list-${stepId}`}>
          {filteredVars.length === 0 ? (
            <div className="text-center py-4 text-[11px] text-fg-4">
              {searchQuery ? "No matching variables found" : "No predefined variables yet"}
            </div>
          ) : (
            filteredVars.map((v) => (
              <button
                key={`${v.scope}-${v.key}`}
                type="button"
                data-testid={`var-item-${v.key}`}
                onClick={() => {
                  onSelectVariable(v.key);
                  setOpen(false);
                }}
                className="w-full text-left p-1.5 rounded hover:bg-bg-elev-3 border border-transparent hover:border-border transition-colors flex items-center justify-between gap-2 group cursor-pointer"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-[11.5px] font-medium text-purple-300 truncate">
                      {`{{${v.key}}}`}
                    </span>
                    <span className="text-[9px] uppercase px-1 py-0.2 rounded border border-border/60 bg-bg-elev-1 text-fg-4">
                      {v.scope}
                    </span>
                    {v.allRowValues && v.allRowValues.length > 1 ? (
                      <span className="text-[9px] px-1 py-0.2 rounded bg-purple-500/20 text-purple-300 font-mono">
                        {v.allRowValues.length} rows
                      </span>
                    ) : null}
                  </div>
                  <div className="text-[10px] text-fg-4 truncate max-w-[200px]">
                    {v.isSecret ? "•••••••• (secret)" : v.value || "no value"}
                  </div>
                </div>
                <ArrowRight className="h-3 w-3 text-fg-5 group-hover:text-purple-400 shrink-0" />
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function QuickEditInputsDialog({
  open,
  onOpenChange,
  caseId,
  caseName,
  suiteId: propSuiteId,
  datasetSchema: propDatasetSchema,
  datasetRows: propDatasetRows,
  steps: propSteps,
  onStepsUpdated,
  canWrite = true,
}: QuickEditInputsDialogProps): React.ReactElement {
  const queryClient = useQueryClient();

  // Always fetch case details when open so dataset_schema, dataset_rows, and suite_id are always loaded
  const { data: fetchedCase, isLoading: isFetchingCase } = useTestCase(
    open ? caseId : undefined,
  );

  const caseData = fetchedCase as unknown as {
    suite_id?: string | null;
    suiteId?: string | null;
    dataset_schema?: string[];
    datasetSchema?: string[];
    dataset_rows?: Array<{ id?: string; name?: string; enabled?: boolean; values?: Record<string, unknown> }>;
    datasetRows?: Array<{ id?: string; name?: string; enabled?: boolean; values?: Record<string, unknown> }>;
  } | undefined;

  const effectiveSuiteId = propSuiteId ?? caseData?.suite_id ?? caseData?.suiteId ?? null;
  const { data: resolvedVars = [] } = useResolvedVariables(effectiveSuiteId);

  const [workingSteps, setWorkingSteps] = useState<DraftStep[]>([]);
  const [editedValues, setEditedValues] = useState<Record<string, string>>({});
  const [editedFiles, setEditedFiles] = useState<Record<string, string[]>>({});
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, boolean>>({});
  const [searchFilter, setSearchFilter] = useState("");
  const [saveAsDdtRow, setSaveAsDdtRow] = useState(false);
  const [ddtRowName, setDdtRowName] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [uploadingStepId, setUploadingStepId] = useState<string | null>(null);

  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Sync internal working steps whenever dialog opens or source data changes
  useEffect(() => {
    if (!open) return;

    let baseSteps: DraftStep[] = [];
    if (propSteps && propSteps.length > 0) {
      baseSteps = propSteps;
    } else if (fetchedCase?.steps) {
      baseSteps = fetchedCase.steps.map((s) => ({
        id: s.id,
        order: s.order,
        action: s.action,
        expected: s.expected,
        code: s.code ?? null,
        mcp_provider: s.mcp_provider,
        target_kind: s.target_kind,
      }));
    }

    setWorkingSteps(baseSteps);

    const initialValues: Record<string, string> = {};
    const initialFiles: Record<string, string[]> = {};
    const detected = detectInputSteps(baseSteps);
    for (const d of detected) {
      initialValues[d.stepId] = d.currentValue;
      if (d.files) {
        initialFiles[d.stepId] = d.files;
      }
    }

    setEditedValues(initialValues);
    setEditedFiles(initialFiles);
    setSaveAsDdtRow(false);
    setDdtRowName("");
    setSearchFilter("");
    setRevealedPasswords({});
  }, [open, propSteps, fetchedCase]);

  // Parse dataset rows
  const parsedDatasetRows = useMemo(() => {
    let rawRows: Array<{ id?: string; name?: string; enabled?: boolean; values?: Record<string, unknown> }> =
      propDatasetRows ||
      caseData?.dataset_rows ||
      caseData?.datasetRows ||
      [];
    if (typeof rawRows === "string") {
      try {
        rawRows = JSON.parse(rawRows);
      } catch {
        rawRows = [];
      }
    }
    return Array.isArray(rawRows) ? rawRows : [];
  }, [propDatasetRows, caseData?.dataset_rows, caseData?.datasetRows]);

  const [selectedRowIndex, setSelectedRowIndex] = useState<number>(0);

  useEffect(() => {
    if (open) {
      if (parsedDatasetRows.length > 0) {
        const firstEnabled = parsedDatasetRows.findIndex((r) => r.enabled !== false);
        setSelectedRowIndex(firstEnabled !== -1 ? firstEnabled : 0);
      } else {
        setSelectedRowIndex(0);
      }
    }
  }, [open, parsedDatasetRows]);

  // Hierarchical variable resolution
  const availableVariables = useMemo(() => {
    const map = new Map<string, AvailableVar>();

    // 1. Workspace / Suite variables
    const varsList = Array.isArray(resolvedVars)
      ? resolvedVars
      : Array.isArray((resolvedVars as unknown as { items?: unknown[] })?.items)
        ? (resolvedVars as unknown as { items: ResolvedVariableItem[] }).items
        : [];
    for (const rv of varsList) {
      map.set(rv.key, {
        key: rv.key,
        value: rv.value ?? null,
        scope: rv.sourceScope || "workspace",
        isSecret: rv.isSecret,
        description: rv.description ?? null,
      });
    }

    // Helper to get values of a variable key across all rows
    const buildAllRowValues = (k: string) => {
      if (parsedDatasetRows.length <= 1) return undefined;
      return parsedDatasetRows.map((r, idx) => ({
        rowName: r.name || `Scenario #${idx + 1}`,
        value:
          r.values && r.values[k] !== undefined && r.values[k] !== null
            ? String(r.values[k])
            : "",
      }));
    };

    // 2. Case Dataset rows & schema (active/selected row values)
    if (parsedDatasetRows.length > 0) {
      const activeRow =
        parsedDatasetRows[selectedRowIndex] ||
        parsedDatasetRows.find((r) => r.enabled !== false) ||
        parsedDatasetRows[0];
      if (activeRow && activeRow.values && typeof activeRow.values === "object") {
        for (const [k, v] of Object.entries(activeRow.values)) {
          map.set(k, {
            key: k,
            value: v !== undefined && v !== null ? String(v) : null,
            scope: "dataset",
            isSecret: isSecretKey(k),
            description: `Case Dataset row "${activeRow.name || `Scenario #${selectedRowIndex + 1}`}"`,
            allRowValues: buildAllRowValues(k),
          });
        }
      }
    }

    let schemaCols: string[] =
      propDatasetSchema ||
      caseData?.dataset_schema ||
      caseData?.datasetSchema ||
      [];
    if (typeof schemaCols === "string") {
      try {
        schemaCols = JSON.parse(schemaCols);
      } catch {
        schemaCols = [];
      }
    }

    if (Array.isArray(schemaCols)) {
      const activeRow =
        parsedDatasetRows[selectedRowIndex] ||
        parsedDatasetRows.find((r) => r.enabled !== false) ||
        parsedDatasetRows[0];
      for (const col of schemaCols) {
        if (!map.has(col)) {
          map.set(col, {
            key: col,
            value: null,
            scope: "dataset",
            isSecret: isSecretKey(col),
            description: `Case Dataset column (empty in "${activeRow?.name || "active row"}")`,
            allRowValues: buildAllRowValues(col),
          });
        }
      }
    }

    return Array.from(map.values());
  }, [
    resolvedVars,
    parsedDatasetRows,
    selectedRowIndex,
    propDatasetSchema,
    caseData?.dataset_schema,
    caseData?.datasetSchema,
  ]);

  const variablesMap = useMemo(() => {
    const m = new Map<string, AvailableVar>();
    for (const v of availableVariables) {
      m.set(v.key, v);
    }
    return m;
  }, [availableVariables]);

  const detectedInputs = useMemo(() => {
    return detectInputSteps(workingSteps);
  }, [workingSteps]);

  const filteredInputs = useMemo(() => {
    const q = searchFilter.trim();
    if (!q) return detectedInputs;
    const regex = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
    return detectedInputs.filter((item) => {
      const editedVal = editedValues[item.stepId] ?? "";
      return regex.test(
        `${item.order} ${item.label} ${item.selector} ${item.originalAction} ${editedVal}`,
      );
    });
  }, [detectedInputs, searchFilter, editedValues]);

  const modifiedCount = useMemo(() => {
    let count = 0;
    for (const item of detectedInputs) {
      const editedVal = editedValues[item.stepId];
      if (editedVal !== undefined && editedVal !== item.currentValue) {
        count++;
      }
    }
    return count;
  }, [detectedInputs, editedValues]);

  const handleValueChange = (stepId: string, val: string) => {
    setEditedValues((prev) => ({ ...prev, [stepId]: val }));
  };

  const handleToggleRevealPassword = (stepId: string) => {
    setRevealedPasswords((prev) => ({ ...prev, [stepId]: !prev[stepId] }));
  };

  const handleInsertVariable = (stepId: string, varKey: string) => {
    const cleanKey = varKey.replace(/^\{\{|\}\}$/g, "").trim();
    setEditedValues((prev) => ({ ...prev, [stepId]: `{{${cleanKey}}}` }));
  };

  const handleFileUpload = async (stepId: string, files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadingStepId(stepId);

    try {
      const filesArray = Array.from(files);
      const readPromises = filesArray.map((f) => {
        return new Promise<{ fileName: string; base64: string }>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (evt) => {
            resolve({
              fileName: f.name,
              base64: typeof evt.target?.result === "string" ? evt.target.result : "",
            });
          };
          reader.onerror = reject;
          reader.readAsDataURL(f);
        });
      });

      const payloadFiles = await Promise.all(readPromises);
      const res = await api.post<{ fixturePaths: string[]; fileNames: string[] }>(
        "/fixtures/upload",
        { files: payloadFiles },
      );

      const uploadedPaths = res.data.fixturePaths;
      setEditedFiles((prev) => ({ ...prev, [stepId]: uploadedPaths }));
      setEditedValues((prev) => ({ ...prev, [stepId]: uploadedPaths.join(", ") }));

      toast.success(
        res.data.fileNames.length > 1
          ? `${res.data.fileNames.length} files attached successfully.`
          : `File '${res.data.fileNames[0]}' attached successfully.`,
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to upload file";
      toast.error(msg);
    } finally {
      setUploadingStepId(null);
      const inputRef = fileInputRefs.current[stepId];
      if (inputRef) inputRef.value = "";
    }
  };

  const handleSave = async () => {
    if (!canWrite) return;
    setIsSaving(true);

    try {
      // 1. Apply each input step update to workingSteps
      let updatedList = [...workingSteps];
      for (const inputItem of detectedInputs) {
        const newVal = editedValues[inputItem.stepId] ?? inputItem.currentValue;
        const newFiles = editedFiles[inputItem.stepId];
        const stepIdx = updatedList.findIndex((s) => s.id === inputItem.stepId);
        const targetStep = updatedList[stepIdx];
        if (stepIdx !== -1 && targetStep) {
          updatedList[stepIdx] = applyStepInputUpdate(targetStep, newVal, newFiles);
        }
      }

      // 2. Commit steps to server
      const payload = {
        steps: updatedList.map((s, idx) => ({
          action: s.action,
          expected: s.expected,
          code: s.code ?? null,
          mcpProvider: s.mcp_provider,
          targetKind: s.target_kind,
          order: idx + 1,
        })),
      };

      await api.patch(`/test-cases/${caseId}/steps`, payload);

      // 3. Optional: Save as DDT Dataset row
      if (saveAsDdtRow) {
        const rowValues: Record<string, string> = {};
        const schemaCols = new Set<string>();

        detectedInputs.forEach((item) => {
          const val = editedValues[item.stepId] ?? item.currentValue;
          // Variable or sanitize selector for column key
          let colKey = `step_${item.order}_input`;
          const varMatch = val.match(/^\{\{([a-zA-Z0-9_.-]+)\}\}$/);
          if (varMatch && varMatch[1]) {
            colKey = varMatch[1];
          } else if (item.selector && item.selector !== "URL") {
            const cleanSelector = item.selector
              .replace(/[^a-zA-Z0-9_]/g, "_")
              .replace(/^_+|_+$/g, "")
              .slice(0, 20);
            if (cleanSelector) colKey = cleanSelector;
          }
          schemaCols.add(colKey);
          rowValues[colKey] = val;
        });

        const existingSchema = caseData?.dataset_schema || caseData?.datasetSchema || [];
        const existingRows = parsedDatasetRows;

        const updatedSchema = Array.from(new Set([...existingSchema, ...schemaCols]));
        const newRow = {
          id: `row-${Date.now()}`,
          name: ddtRowName.trim() || `Scenario ${existingRows.length + 1}`,
          enabled: true,
          values: rowValues,
        };

        await api.patch(`/test-cases/${caseId}`, {
          datasetSchema: updatedSchema,
          datasetRows: [...existingRows, newRow],
        });
      }

      // Notify caller if callback provided
      onStepsUpdated?.(updatedList);

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] }),
        queryClient.invalidateQueries({ queryKey: ["test-cases"] }),
      ]);

      toast.success(
        saveAsDdtRow
          ? "Saved inputs and created new Test Data scenario."
          : "Test case inputs updated successfully.",
      );
      onOpenChange(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save inputs";
      toast.error(msg);
    } finally {
      setIsSaving(false);
    }
  };

  const displayName = caseName || fetchedCase?.name || caseId;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="quick-edit-inputs-dialog"
        className="max-h-[88vh] flex flex-col sm:max-w-3xl overflow-hidden p-0 border border-border bg-bg-elev-1 shadow-2xl"
      >
        <DialogHeader className="p-5 pb-3 border-b border-border bg-bg-elev-1 shrink-0">
          <div className="flex items-center gap-2.5 pr-10">
            <DialogTitle className="flex items-center gap-2 text-[15px] font-semibold text-fg-1">
              <SlidersHorizontal className="h-4 w-4 text-accent" />
              Quick Edit Inputs
            </DialogTitle>
            <span className="rounded border border-border bg-bg-elev-2 px-2 py-0.5 font-mono text-[11px] font-normal text-fg-3">
              {caseId}
            </span>
          </div>
          <DialogDescription className="text-xs text-fg-4">
            Detect and update interactive data (text, credentials, dropdowns, uploads) in{" "}
            <span className="font-medium text-fg-2">{displayName}</span> without scrolling through
            all steps.
          </DialogDescription>
        </DialogHeader>

        {/* Body content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-bg-base/70">
          {/* Search / Filter header when >2 steps detected */}
          {detectedInputs.length > 2 ? (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-4" />
              <Input
                data-testid="filter-inputs-field"
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Filter inputs by element selector, step #, or value..."
                className="h-8 pl-8 pr-8 text-xs bg-bg-elev-2 border-border text-fg-1 placeholder:text-fg-4 focus-visible:border-accent/60"
              />
              {searchFilter ? (
                <button
                  type="button"
                  onClick={() => setSearchFilter("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-4 hover:text-fg-2"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          ) : null}

          {/* Active Scenario Row Selector (when multiple DDT rows exist) */}
          {parsedDatasetRows.length > 1 ? (
            <div
              data-testid="ddt-scenario-banner"
              className="flex flex-wrap items-center justify-between gap-2.5 px-3.5 py-2.5 rounded-lg border border-purple-500/30 bg-purple-500/[0.08]"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Database className="h-4 w-4 text-purple-400 shrink-0" />
                <div className="flex flex-col min-w-0">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-fg-1">
                    <span>Active Scenario: </span>
                    <span className="text-purple-300 font-mono truncate max-w-[200px]">
                      {parsedDatasetRows[selectedRowIndex]?.name || `Scenario #${selectedRowIndex + 1}`}
                    </span>
                  </div>
                  <span className="text-[10.5px] text-fg-4">
                    Variable previews like <code className="text-purple-300 font-mono">{"{{...}}"}</code> resolve from this scenario
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[11px] text-fg-4 font-medium">Switch Row:</span>
                <select
                  data-testid="ddt-scenario-select"
                  value={selectedRowIndex}
                  onChange={(e) => setSelectedRowIndex(Number(e.target.value))}
                  className="h-7 text-xs bg-bg-elev-3 border border-border text-fg-1 rounded px-2 font-medium focus:outline-none focus:ring-1 focus:ring-purple-400 cursor-pointer"
                >
                  {parsedDatasetRows.map((r, idx) => (
                    <option key={r.id || idx} value={idx}>
                      {r.name || `Scenario #${idx + 1}`} ({idx + 1} of {parsedDatasetRows.length})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ) : null}

          {isFetchingCase && !workingSteps.length ? (
            <div className="flex flex-col items-center justify-center py-12 text-center text-fg-4">
              <Loader2 className="h-6 w-6 animate-spin text-accent mb-2" />
              <p className="text-xs">Loading test case steps...</p>
            </div>
          ) : detectedInputs.length === 0 ? (
            <div
              data-testid="no-inputs-detected"
              className="flex flex-col items-center justify-center py-12 text-center rounded-lg border border-dashed border-border bg-bg-elev-1/50 p-6"
            >
              <FolderInput className="h-8 w-8 text-fg-5 mb-2" />
              <h5 className="text-sm font-medium text-fg-2">No editable input steps detected</h5>
              <p className="text-xs text-fg-4 max-w-sm mt-1">
                Steps with typing (`browser_type`), dropdown select, file upload, or navigation will
                automatically show up here for rapid editing.
              </p>
            </div>
          ) : (
            <div className="space-y-3" data-testid="detected-inputs-list">
              <div className="flex items-center justify-between text-[11px] text-fg-4 px-1">
                <span>
                  Showing <strong className="text-fg-2">{filteredInputs.length}</strong> of{" "}
                  <strong className="text-fg-2">{detectedInputs.length}</strong> input{" "}
                  {detectedInputs.length === 1 ? "step" : "steps"}
                </span>
                <span className="flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-purple-400" />
                  Hover variable badge to preview raw value
                </span>
              </div>

              {filteredInputs.map((item) => {
                const badge = getTypeBadge(item.type);
                const isPassword = item.isPassword;
                const isRevealed = revealedPasswords[item.stepId];
                const currentVal = editedValues[item.stepId] ?? item.currentValue;
                const isUploading = uploadingStepId === item.stepId;
                const fileList = editedFiles[item.stepId] || item.files || [];

                // Detect variable bindings in current value
                const varMatches = Array.from(
                  currentVal.matchAll(/\{\{([a-zA-Z0-9_.-]+)\}\}/g),
                )
                  .map((m) => m[1])
                  .filter((k): k is string => Boolean(k));
                const hasVariable = varMatches.length > 0;

                return (
                  <div
                    key={item.stepId}
                    data-testid={`input-step-row-${item.stepId}`}
                    className={cn(
                      "rounded-lg border p-4 space-y-3 transition-all",
                      hasVariable
                        ? "border-purple-500/40 bg-purple-500/[0.04] shadow-[0_0_12px_rgba(168,85,247,0.06)]"
                        : "border-border bg-bg-elev-1 shadow-xs hover:border-border-strong",
                    )}
                  >
                    {/* Header: Step order, type badge, selector label */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-bg-elev-2 font-mono text-[10.5px] font-medium text-fg-3 border border-border/40">
                          {item.order}
                        </span>
                        <span
                          className={cn(
                            "rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                            badge.color,
                          )}
                        >
                          {badge.label}
                        </span>
                        <span
                          className="truncate text-[12px] font-medium text-fg-1"
                          title={item.selector}
                        >
                          {item.label}
                        </span>
                      </div>
                      <span className="shrink-0 text-[10.5px] text-fg-5 font-mono max-w-[150px] truncate" title={item.selector}>
                        {item.selector}
                      </span>
                    </div>

                    {/* Action description context */}
                    <p className="text-[11px] text-fg-4 italic truncate">&ldquo;{item.originalAction}&rdquo;</p>

                    {/* Smart Input Control based on type */}
                    {item.type === "upload" ? (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-bg-elev-2 p-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Paperclip className="h-3.5 w-3.5 text-accent" />
                          {fileList.length > 0 ? (
                            fileList.map((fPath, i) => (
                              <span
                                key={`${fPath}-${i}`}
                                className="inline-flex items-center gap-1 rounded bg-bg-elev-3 px-2 py-0.5 font-mono text-[11px] text-fg-2 border border-border"
                                title={fPath}
                              >
                                {fPath.split("/").pop() || fPath}
                              </span>
                            ))
                          ) : (
                            <span className="text-[11px] italic text-fg-5">No files attached</span>
                          )}
                        </div>

                        <div>
                          <input
                            ref={(el) => {
                              fileInputRefs.current[item.stepId] = el;
                            }}
                            type="file"
                            multiple
                            className="hidden"
                            data-testid={`upload-input-${item.stepId}`}
                            onChange={(e) => void handleFileUpload(item.stepId, e.target.files)}
                            disabled={!canWrite || isUploading}
                          />
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            data-testid={`change-files-btn-${item.stepId}`}
                            disabled={!canWrite || isUploading}
                            onClick={() => fileInputRefs.current[item.stepId]?.click()}
                            className="h-6 gap-1 text-[11px]"
                          >
                            {isUploading ? (
                              <>
                                <Loader2 className="h-3 w-3 animate-spin text-accent" />
                                Uploading...
                              </>
                            ) : (
                              <>
                                <FileUp className="h-3 w-3 text-accent" />
                                Change Files
                              </>
                            )}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <div className="relative flex-1">
                            <Input
                              data-testid={`input-field-${item.stepId}`}
                              type={isPassword && !isRevealed ? "password" : "text"}
                              value={currentVal}
                              disabled={!canWrite}
                              onChange={(e) => handleValueChange(item.stepId, e.target.value)}
                              placeholder={
                                item.type === "url"
                                  ? "https://..."
                                  : isPassword
                                    ? "Enter password"
                                    : "Enter value"
                              }
                              className={cn(
                                "h-8 text-[12.5px] bg-bg-elev-2 border-border text-fg-1 transition-all",
                                isPassword && "pr-8",
                                hasVariable &&
                                  "border-purple-500/50 bg-purple-500/[0.08] text-purple-200 focus-visible:border-purple-500 focus-visible:ring-purple-500/20 font-mono",
                              )}
                            />
                            {isPassword ? (
                              <button
                                type="button"
                                tabIndex={-1}
                                onClick={() => handleToggleRevealPassword(item.stepId)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-4 hover:text-fg-2 transition-colors cursor-pointer"
                                title={isRevealed ? "Hide password" : "Show password"}
                                data-testid={`toggle-password-${item.stepId}`}
                              >
                                {isRevealed ? (
                                  <EyeOff className="h-3.5 w-3.5" />
                                ) : (
                                  <Eye className="h-3.5 w-3.5" />
                                )}
                              </button>
                            ) : null}
                          </div>

                          <VariablePickerPopover
                            stepId={item.stepId}
                            onSelectVariable={(varKey) => handleInsertVariable(item.stepId, varKey)}
                            availableVariables={availableVariables}
                            disabled={!canWrite}
                          />
                        </div>

                        {/* Variable badges with interactive hover preview */}
                        {hasVariable ? (
                          <div
                            className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-border/30"
                            data-testid={`bound-variable-badges-${item.stepId}`}
                          >
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-purple-400 select-none">
                              Bound:
                            </span>
                            {varMatches.map((varKey) => {
                              const resolved = variablesMap.get(varKey);
                              const isSecret = resolved ? resolved.isSecret : isSecretKey(varKey);
                              const scope = resolved ? resolved.scope : "unbound";
                              const val = resolved?.value ?? null;
                              const desc =
                                resolved?.description ??
                                (scope === "unbound"
                                  ? "Custom variable placeholder (not yet defined in Test Data, Suite, or Workspace)"
                                  : null);
                              return (
                                <VariableBadge
                                  key={varKey}
                                  variableKey={varKey}
                                  scope={scope}
                                  value={val}
                                  isSecret={isSecret}
                                  description={desc}
                                  allRowValues={resolved?.allRowValues}
                                />
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Optional: Save as DDT scenario row */}
          {detectedInputs.length > 0 && canWrite ? (
            <div className="rounded-lg border border-accent/20 bg-accent/[0.03] p-3.5 space-y-2.5 bg-bg-elev-1">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="save-as-ddt"
                  data-testid="save-as-ddt-checkbox"
                  checked={saveAsDdtRow}
                  onCheckedChange={(checked) => setSaveAsDdtRow(Boolean(checked))}
                />
                <label
                  htmlFor="save-as-ddt"
                  className="text-xs font-medium text-fg-2 cursor-pointer select-none"
                >
                  Save as new Test Data scenario (DDT row)
                </label>
              </div>

              {saveAsDdtRow ? (
                <div className="pl-6 space-y-1.5">
                  <Input
                    data-testid="ddt-row-name-input"
                    placeholder="Scenario Name (e.g. Invalid Login, Test User #2)"
                    value={ddtRowName}
                    onChange={(e) => setDdtRowName(e.target.value)}
                    className="h-7 text-xs bg-bg-elev-2 border-border"
                  />
                  <p className="text-[11px] text-fg-4">
                    Will add a new row in the <strong>Test Data</strong> tab for Data-Driven Testing
                    runs.
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter className="p-4 border-t border-border bg-bg-elev-1 shrink-0 flex items-center justify-between sm:justify-between">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>

          <Button
            type="button"
            size="sm"
            data-testid="quick-edit-apply-btn"
            disabled={!canWrite || isSaving || detectedInputs.length === 0}
            onClick={() => void handleSave()}
            className="gap-1.5"
          >
            {isSaving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Applying...
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5" />
                {modifiedCount > 0
                  ? `Apply Changes (${modifiedCount} modified)`
                  : "Apply Changes"}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

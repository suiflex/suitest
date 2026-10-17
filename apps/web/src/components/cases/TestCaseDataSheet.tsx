import React, { useState, useMemo, useEffect } from "react";
import {
  Table as TableIcon,
  Plus,
  Trash2,
  Copy,
  Save,
  Check,
  Eye,
  EyeOff,
  Info,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { VariableBadge } from "@/components/shared/VariableBadge";
import { useUpdateTestCase } from "@/hooks/use-test-cases";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

type CaseDetail = components["schemas"]["TestCaseDetail"];

export interface TestCaseDataSheetProps {
  testCase: CaseDetail;
  steps?: Array<{ action?: string; code?: string | null }>;
  canWrite?: boolean;
  className?: string;
}

interface DatasetRow {
  id: string;
  name: string;
  enabled: boolean;
  values: Record<string, string>;
}

export function TestCaseDataSheet({
  testCase,
  steps = [],
  canWrite = true,
  className,
}: TestCaseDataSheetProps) {
  const updateTestCase = useUpdateTestCase(testCase.id);

  // 1. Detect variables from steps
  const detectedKeys = useMemo(() => {
    const keys = new Set<string>();
    const regex = /\{\{([a-zA-Z0-9_.-]+)\}\}/g;
    for (const step of steps) {
      if (step.action) {
        let match;
        while ((match = regex.exec(step.action)) !== null) {
          if (match[1]) keys.add(match[1]);
        }
      }
      if (step.code) {
        let match;
        while ((match = regex.exec(step.code)) !== null) {
          if (match[1]) keys.add(match[1]);
        }
      }
    }
    return Array.from(keys);
  }, [steps]);

  const detectedKeysSignature = useMemo(() => detectedKeys.slice().sort().join(","), [detectedKeys]);

  // Combined columns (schema from DB + newly detected + user added)
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<DatasetRow[]>([]);
  const [newColumnName, setNewColumnName] = useState("");
  const [isAddingColumn, setIsAddingColumn] = useState(false);
  const [revealedCells, setRevealedCells] = useState<Record<string, boolean>>({});
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const currentCaseIdRef = React.useRef(testCase.id);

  const carrier = testCase as unknown as {
    dataset_schema?: string[] | null;
    datasetSchema?: string[] | null;
    dataset_rows?: Array<Record<string, unknown>> | null;
    datasetRows?: Array<Record<string, unknown>> | null;
  };
  const rawSchemaSignature = JSON.stringify(carrier.dataset_schema || carrier.datasetSchema || []);
  const rawRowsSignature = JSON.stringify(carrier.dataset_rows || carrier.datasetRows || []);

  // Initialize columns and rows from testCase
  useEffect(() => {
    const isNewCase = currentCaseIdRef.current !== testCase.id;
    currentCaseIdRef.current = testCase.id;

    const rawSchema = carrier.dataset_schema || carrier.datasetSchema || [];
    const allCols = Array.from(new Set([...rawSchema, ...detectedKeys]));
    setColumns((prev) => (isNewCase ? allCols : Array.from(new Set([...prev, ...allCols]))));

    const rawRows = carrier.dataset_rows || carrier.datasetRows || [];

    if (isNewCase || (!hasUnsavedChanges && rawRows.length > 0) || rows.length === 0) {
      const initialRows: DatasetRow[] = [];
      if (Array.isArray(rawRows) && rawRows.length > 0) {
        for (let i = 0; i < rawRows.length; i++) {
          const r = rawRows[i] as { id?: string; name?: string; enabled?: boolean; values?: Record<string, string> };
          initialRows.push({
            id: r.id || `row-${i + 1}`,
            name: r.name || (i === 0 ? "Default" : `Row ${i + 1}`),
            enabled: r.enabled !== false,
            values: r.values || {},
          });
        }
      } else {
        initialRows.push({
          id: "row-1",
          name: "Default (Single Run)",
          enabled: true,
          values: {},
        });
      }
      setRows(initialRows);
      setHasUnsavedChanges(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testCase.id, rawSchemaSignature, rawRowsSignature, detectedKeysSignature]);

  const toggleCellReveal = (cellKey: string) => {
    setRevealedCells((prev) => ({ ...prev, [cellKey]: !prev[cellKey] }));
  };

  const handleCellValueChange = (rowId: string, col: string, val: string) => {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId
          ? { ...r, values: { ...r.values, [col]: val } }
          : r
      )
    );
    setHasUnsavedChanges(true);
  };

  const handleRowNameChange = (rowId: string, name: string) => {
    setRows((prev) =>
      prev.map((r) => (r.id === rowId ? { ...r, name } : r))
    );
    setHasUnsavedChanges(true);
  };

  const handleRowToggle = (rowId: string) => {
    setRows((prev) =>
      prev.map((r) => (r.id === rowId ? { ...r, enabled: !r.enabled } : r))
    );
    setHasUnsavedChanges(true);
  };

  const handleAddRow = () => {
    const nextIdx = rows.length + 1;
    const newRow: DatasetRow = {
      id: `row-${Date.now()}`,
      name: `Dataset Matrix #${nextIdx}`,
      enabled: true,
      values: {},
    };
    setRows((prev) => [...prev, newRow]);
    setHasUnsavedChanges(true);
  };

  const handleDuplicateRow = (row: DatasetRow) => {
    const duplicated: DatasetRow = {
      id: `row-${Date.now()}`,
      name: `${row.name} (Copy)`,
      enabled: true,
      values: { ...row.values },
    };
    setRows((prev) => [...prev, duplicated]);
    setHasUnsavedChanges(true);
  };

  const handleDeleteRow = (rowId: string) => {
    if (rows.length <= 1) {
      toast.error("At least one test data row must remain.");
      return;
    }
    setRows((prev) => prev.filter((r) => r.id !== rowId));
    setHasUnsavedChanges(true);
  };

  const handleAddColumn = () => {
    const trimmed = newColumnName.trim();
    if (!trimmed) return;
    if (!/^[a-zA-Z0-9_.-]+$/.test(trimmed)) {
      toast.error("Variable key may only contain letters, numbers, underscores, and hyphens.");
      return;
    }
    if (columns.includes(trimmed)) {
      toast.error(`Column "${trimmed}" already exists.`);
      return;
    }
    setColumns((prev) => [...prev, trimmed]);
    setNewColumnName("");
    setIsAddingColumn(false);
    setHasUnsavedChanges(true);
  };

  const handleRemoveColumn = (colToRemove: string) => {
    setColumns((prev) => prev.filter((c) => c !== colToRemove));
    setRows((prev) =>
      prev.map((r) => {
        const nextVals = { ...r.values };
        delete nextVals[colToRemove];
        return { ...r, values: nextVals };
      })
    );
    setHasUnsavedChanges(true);
  };

  const handleSave = async () => {
    try {
      await updateTestCase.mutateAsync({
        datasetSchema: columns,
        datasetRows: rows.map((r) => ({
          id: r.id,
          name: r.name,
          enabled: r.enabled,
          values: r.values,
        })),
      });
      setHasUnsavedChanges(false);
      toast.success("Test dataset sheet saved successfully.");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save test data sheet.");
    }
  };

  const isSecretKey = (key: string) => {
    const lower = key.toLowerCase();
    return (
      lower.includes("pass") ||
      lower.includes("secret") ||
      lower.includes("token") ||
      lower.includes("apikey") ||
      lower.includes("key")
    );
  };

  return (
    <div className={cn("space-y-4", className)} data-testid="test-case-data-sheet">
      {/* Header toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-card p-3 rounded-lg border border-border/60">
        <div>
          <div className="flex items-center gap-2">
            <TableIcon className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">
              In-Case Test Data Matrix (DDT)
            </h3>
            {rows.length > 1 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
                Multi-Role Matrix ({rows.filter((r) => r.enabled).length}/{rows.length} Active)
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Configure test data rows to execute this test case across multiple roles (e.g. Admin vs Manager) or boundary inputs.
          </p>
        </div>

        {canWrite && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleAddRow}
              className="h-8 gap-1.5 text-xs"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Row
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!hasUnsavedChanges || updateTestCase.isPending}
              className={cn(
                "h-8 gap-1.5 text-xs font-medium transition-all",
                hasUnsavedChanges && "ring-2 ring-primary/40 shadow-sm"
              )}
            >
              {updateTestCase.isPending ? (
                <span>Saving...</span>
              ) : (
                <>
                  <Save className="w-3.5 h-3.5" />
                  <span>{hasUnsavedChanges ? "Save Changes" : "Saved"}</span>
                </>
              )}
            </Button>
          </div>
        )}
      </div>

      {/* Sheet Content */}
      <div className="rounded-lg border border-border/80 bg-card overflow-hidden shadow-sm">
        <div className="overflow-x-auto max-h-[600px]">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/60 sticky top-0 z-10 border-b border-border text-muted-foreground text-[11px] font-medium">
              <tr>
                <th className="px-3 py-2.5 w-10 text-center">Run</th>
                <th className="px-3 py-2.5 min-w-[180px]">Dataset Name / Scenario</th>
                {columns.map((col) => (
                  <th key={col} className="px-3 py-2.5 min-w-[200px]">
                    <div className="flex items-center justify-between gap-1 group">
                      <VariableBadge variableKey={col} scope="dataset" />
                      {canWrite && (
                        <button
                          type="button"
                          onClick={() => handleRemoveColumn(col)}
                          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive p-0.5 rounded transition-opacity"
                          title={`Remove ${col} column`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  </th>
                ))}
                {canWrite && (
                  <th className="px-3 py-2.5 w-36">
                    {isAddingColumn ? (
                      <div className="flex items-center gap-1">
                        <Input
                          size={1}
                          placeholder="var_name"
                          value={newColumnName}
                          onChange={(e) => setNewColumnName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleAddColumn();
                            if (e.key === "Escape") setIsAddingColumn(false);
                          }}
                          autoFocus
                          className="h-6 text-xs font-mono px-1.5 py-0"
                        />
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6"
                          onClick={handleAddColumn}
                        >
                          <Check className="w-3 h-3 text-emerald-400" />
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setIsAddingColumn(true)}
                        className="h-6 px-1.5 text-[11px] gap-1 text-primary hover:text-primary"
                      >
                        <Plus className="w-3 h-3" />
                        Add Column
                      </Button>
                    )}
                  </th>
                )}
                {canWrite && <th className="px-3 py-2.5 w-20 text-right">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40 font-mono">
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    "hover:bg-muted/20 transition-colors group",
                    !row.enabled && "opacity-50 bg-muted/10"
                  )}
                >
                  {/* Enable Checkbox */}
                  <td className="px-3 py-2 text-center">
                    <Checkbox
                      checked={row.enabled}
                      onCheckedChange={() => canWrite && handleRowToggle(row.id)}
                      disabled={!canWrite}
                    />
                  </td>

                  {/* Row Name */}
                  <td className="px-3 py-2">
                    <Input
                      value={row.name}
                      onChange={(e) => handleRowNameChange(row.id, e.target.value)}
                      disabled={!canWrite}
                      className="h-7 text-xs font-sans font-medium bg-transparent border-transparent hover:border-border focus:border-primary focus:bg-background transition-colors"
                      placeholder="e.g. Admin User"
                    />
                  </td>

                  {/* Variable Column Inputs */}
                  {columns.map((col) => {
                    const isSecret = isSecretKey(col);
                    const cellId = `${row.id}-${col}`;
                    const isRevealed = Boolean(revealedCells[cellId]);
                    const cellVal = row.values[col] || "";

                    return (
                      <td key={col} className="px-3 py-2">
                        <div className="relative flex items-center">
                          <Input
                            type={isSecret && !isRevealed ? "password" : "text"}
                            value={cellVal}
                            onChange={(e) =>
                              handleCellValueChange(row.id, col, e.target.value)
                            }
                            disabled={!canWrite}
                            placeholder={`{{${col}}}`}
                            className={cn(
                              "h-7 text-xs font-mono pr-7 bg-transparent border-transparent hover:border-border focus:border-primary focus:bg-background transition-colors",
                              isSecret && !isRevealed && "tracking-widest"
                            )}
                          />
                          {isSecret && (
                            <button
                              type="button"
                              onClick={() => toggleCellReveal(cellId)}
                              className="absolute right-2 text-muted-foreground hover:text-foreground"
                            >
                              {isRevealed ? (
                                <EyeOff className="w-3.5 h-3.5" />
                              ) : (
                                <Eye className="w-3.5 h-3.5" />
                              )}
                            </button>
                          )}
                        </div>
                      </td>
                    );
                  })}

                  {canWrite && <td className="px-3 py-2" />}

                  {/* Row Actions */}
                  {canWrite && (
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-muted-foreground hover:text-foreground"
                          onClick={() => handleDuplicateRow(row)}
                          title="Duplicate row"
                        >
                          <Copy className="w-3 h-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-muted-foreground hover:text-destructive"
                          onClick={() => handleDeleteRow(row.id)}
                          title="Delete row"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {columns.length === 0 && (
        <div className="p-4 rounded-lg bg-secondary/30 border border-border flex items-start gap-3 text-xs text-muted-foreground">
          <Info className="w-4 h-4 text-primary shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-foreground">Tip: Reference variables in steps</span>
            <p className="mt-0.5">
              Type <code className="text-primary font-mono">{`{{username}}`}</code> or{" "}
              <code className="text-primary font-mono">{`{{password}}`}</code> in any step action or code input.
              Suitest will automatically detect them and add them as columns to this data sheet!
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

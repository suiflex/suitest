import React, { useState } from "react";
import {
  KeyRound,
  Plus,
  Trash2,
  Edit2,
  Lock,
  Layers,
} from "lucide-react";

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
import { usePermissions } from "@/hooks/use-permissions";
import {
  useWorkspaceVariables,
  useCreateWorkspaceVariable,
  useUpdateWorkspaceVariable,
  useDeleteWorkspaceVariable,
  useSuiteVariables,
  useCreateSuiteVariable,
  useUpdateSuiteVariable,
  useDeleteSuiteVariable,
  type VariablePublic,
} from "@/hooks/use-variables";
import { cn } from "@/lib/utils";

export interface VariablesTableProps {
  scope: "workspace" | "suite";
  suiteId?: string | null;
  workspaceId?: string | null;
  className?: string;
}

export function VariablesTable({
  scope,
  suiteId,
  workspaceId,
  className,
}: VariablesTableProps) {
  const permissions = usePermissions();
  const canWrite =
    permissions.canWriteTests || permissions.isAdmin || permissions.isOwner;

  // Workspace hooks
  const wsQuery = useWorkspaceVariables(workspaceId);
  const createWsVar = useCreateWorkspaceVariable(workspaceId);
  const updateWsVar = useUpdateWorkspaceVariable(workspaceId);
  const deleteWsVar = useDeleteWorkspaceVariable(workspaceId);

  // Suite hooks
  const suiteQuery = useSuiteVariables(suiteId);
  const createSuiteVar = useCreateSuiteVariable(suiteId);
  const updateSuiteVar = useUpdateSuiteVariable(suiteId);
  const deleteSuiteVar = useDeleteSuiteVariable(suiteId);

  const variables = scope === "suite" ? suiteQuery.data || [] : wsQuery.data || [];
  const isLoading = scope === "suite" ? suiteQuery.isLoading : wsQuery.isLoading;

  // Dialog states
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingVar, setEditingVar] = useState<VariablePublic | null>(null);
  const [deletingVar, setDeletingVar] = useState<VariablePublic | null>(null);

  // Form states
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [isSecret, setIsSecret] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const openAdd = () => {
    setKey("");
    setValue("");
    setDescription("");
    setIsSecret(false);
    setFormError(null);
    setIsAddOpen(true);
  };

  const openEdit = (v: VariablePublic) => {
    setEditingVar(v);
    setKey(v.key);
    setValue(v.value || "");
    setDescription(v.description || "");
    setIsSecret(v.isSecret);
    setFormError(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const trimmedKey = key.trim();
    if (!trimmedKey) {
      setFormError("Variable key is required");
      return;
    }
    if (!/^[a-zA-Z0-9_.-]+$/.test(trimmedKey)) {
      setFormError(
        "Key can only contain letters, numbers, underscores, dots, or hyphens"
      );
      return;
    }

    try {
      if (editingVar) {
        if (scope === "suite") {
          await updateSuiteVar.mutateAsync({
            variableId: editingVar.id,
            input: {
              key: trimmedKey,
              value: value !== "" ? value : undefined,
              description: description || undefined,
              isSecret,
            },
          });
        } else {
          await updateWsVar.mutateAsync({
            variableId: editingVar.id,
            input: {
              key: trimmedKey,
              value: value !== "" ? value : undefined,
              description: description || undefined,
              isSecret,
            },
          });
        }
        setEditingVar(null);
      } else {
        if (scope === "suite") {
          await createSuiteVar.mutateAsync({
            key: trimmedKey,
            value,
            description: description || undefined,
            isSecret,
          });
        } else {
          await createWsVar.mutateAsync({
            key: trimmedKey,
            value,
            description: description || undefined,
            isSecret,
          });
        }
        setIsAddOpen(false);
      }
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to save variable");
    }
  };

  const handleDelete = async () => {
    if (!deletingVar) return;
    try {
      if (scope === "suite") {
        await deleteSuiteVar.mutateAsync(deletingVar.id);
      } else {
        await deleteWsVar.mutateAsync(deletingVar.id);
      }
      setDeletingVar(null);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to delete variable");
    }
  };

  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold flex items-center gap-2">
            {scope === "suite" ? (
              <>
                <Layers className="w-4 h-4 text-sky-400" />
                <span>Suite Variables</span>
              </>
            ) : (
              <>
                <KeyRound className="w-4 h-4 text-emerald-400" />
                <span>Workspace Shared Variables & Secrets</span>
              </>
            )}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {scope === "suite"
              ? "Variables defined here override workspace defaults for all test cases in this suite."
              : "Centrally manage endpoints, credentials, and parameters referenced via {{variable_name}} across suites."}
          </p>
        </div>

        {canWrite && (
          <Button
            size="sm"
            onClick={openAdd}
            className="self-start sm:self-auto gap-1.5 h-8 text-xs font-medium"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Variable
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-muted-foreground animate-pulse">
          Loading variables...
        </div>
      ) : variables.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/80 p-8 text-center bg-card/30">
          <KeyRound className="w-8 h-8 text-muted-foreground/40 mx-auto mb-2" />
          <h3 className="text-sm font-medium text-foreground">No variables defined yet</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
            {scope === "suite"
              ? "Add suite-specific overrides for URLs, credentials, or flags."
              : "Define shared keys like {{base_url}}, {{api_key}}, or {{admin_email}} to use across test cases."}
          </p>
          {canWrite && (
            <Button
              variant="outline"
              size="sm"
              onClick={openAdd}
              className="mt-4 gap-1.5 text-xs"
            >
              <Plus className="w-3.5 h-3.5" />
              Add First Variable
            </Button>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border/60 bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/40 border-b border-border/60 text-muted-foreground font-medium uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="px-4 py-2.5">Variable Key</th>
                  <th className="px-4 py-2.5">Value</th>
                  <th className="px-4 py-2.5">Type</th>
                  <th className="px-4 py-2.5">Description</th>
                  {canWrite && <th className="px-4 py-2.5 text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {variables.map((v) => {
                  return (
                    <tr
                      key={v.id}
                      className="hover:bg-muted/20 transition-colors group"
                    >
                      <td className="px-4 py-3 font-mono font-medium text-foreground whitespace-nowrap">
                        <span className="text-primary">{`{{${v.key}}}`}</span>
                      </td>
                      <td className="px-4 py-3 font-mono max-w-xs truncate">
                        {v.isSecret ? (
                          <div className="flex items-center gap-2">
                            <span className="text-muted-foreground tracking-widest select-none">
                              ••••••••
                            </span>
                            <span className="text-[10px] text-amber-400 font-sans px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
                              AES-GCM Encrypted
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <span className="truncate">{v.value || "—"}</span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {v.isSecret ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20">
                            <Lock className="w-2.5 h-2.5" />
                            Secret
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-secondary text-secondary-foreground border border-border/40">
                            Plain Text
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-xs truncate">
                        {v.description || "—"}
                      </td>
                      {canWrite && (
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                              onClick={() => openEdit(v)}
                              title="Edit variable"
                            >
                              <Edit2 className="w-3.5 h-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-destructive"
                              onClick={() => setDeletingVar(v)}
                              title="Delete variable"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add / Edit Variable Dialog */}
      <Dialog
        open={isAddOpen || editingVar !== null}
        onOpenChange={(open) => {
          if (!open) {
            setIsAddOpen(false);
            setEditingVar(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <form onSubmit={handleSave}>
            <DialogHeader>
              <DialogTitle className="text-base font-semibold">
                {editingVar ? "Edit Variable" : "Add Variable"}
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                {scope === "suite"
                  ? "Suite variables override workspace variables with the same key."
                  : "Workspace variables are accessible across all test suites."}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-4 text-xs">
              {formError && (
                <div className="p-2.5 rounded bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                  {formError}
                </div>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="var-key" className="text-xs font-medium">
                  Variable Key
                </Label>
                <div className="relative">
                  <Input
                    id="var-key"
                    placeholder="e.g. base_url, admin_pwd"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    className="font-mono text-xs pl-8"
                    required
                  />
                  <span className="absolute left-2.5 top-2.5 text-muted-foreground font-mono text-xs">
                    {`{{`}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Reference this variable in step actions and targets as {`{{${key || "key"}}}`}.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="var-val" className="text-xs font-medium">
                  Value {editingVar && editingVar.isSecret && "(leave blank to keep unchanged)"}
                </Label>
                <Input
                  id="var-val"
                  type={isSecret ? "password" : "text"}
                  placeholder={
                    editingVar && editingVar.isSecret
                      ? "•••••••• (unchanged)"
                      : "Enter value..."
                  }
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="var-desc" className="text-xs font-medium">
                  Description (optional)
                </Label>
                <Input
                  id="var-desc"
                  placeholder="e.g. Staging environment base URL"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="text-xs"
                />
              </div>

              <div className="flex items-start gap-2 pt-2 border-t border-border/60">
                <input
                  type="checkbox"
                  id="var-secret"
                  checked={isSecret}
                  onChange={(e) => setIsSecret(e.target.checked)}
                  className="mt-0.5 rounded border-border"
                />
                <Label
                  htmlFor="var-secret"
                  className="text-xs font-normal cursor-pointer leading-tight"
                >
                  <span className="font-medium text-foreground block">
                    Mask value & encrypt as secret
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    Encrypted with AES-GCM at rest and masked in responses.
                  </span>
                </Label>
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setIsAddOpen(false);
                  setEditingVar(null);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" size="sm">
                {editingVar ? "Update Variable" : "Save Variable"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deletingVar !== null}
        onOpenChange={(open) => {
          if (!open) setDeletingVar(null);
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              Delete Variable
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Are you sure you want to delete {`{{${deletingVar?.key}}}`}? Test cases
              referencing this variable will fail to resolve it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeletingVar(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
            >
              Delete Variable
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

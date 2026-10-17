import { useEffect, useState } from "react";

import { VariablesTable } from "@/components/settings/VariablesTable";
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
import { useDeleteSuite, useUpdateSuite } from "@/hooks/use-test-cases";
import type { components } from "@/lib/api-types";

type TestingApproach = components["schemas"]["TestingApproach"];
type SuitePublic = components["schemas"]["SuitePublic"];

export interface EditSuiteDialogProps {
  open: boolean;
  onClose: () => void;
  suite: SuitePublic | null;
}

export function EditSuiteDialog({ open, onClose, suite }: EditSuiteDialogProps): React.ReactElement {
  const [name, setName] = useState("");
  const [approach, setApproach] = useState<TestingApproach>("BLACK_BOX");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const updateSuite = useUpdateSuite();
  const deleteSuite = useDeleteSuite();
  const resetUpdate = updateSuite.reset;
  const resetDelete = deleteSuite.reset;

  useEffect(() => {
    if (suite && open) {
      setName(suite.name);
      setApproach(suite.default_testing_approach ?? "BLACK_BOX");
      setConfirmDelete(false);
      resetUpdate();
      resetDelete();
    }
  }, [suite, open, resetUpdate, resetDelete]);

  const handleClose = (): void => {
    setConfirmDelete(false);
    updateSuite.reset();
    deleteSuite.reset();
    onClose();
  };

  const handleSubmit = (event: React.FormEvent): void => {
    event.preventDefault();
    if (!suite) return;
    const trimmed = name.trim();
    if (trimmed.length === 0) return;

    updateSuite.mutate(
      {
        suiteId: suite.id,
        name: trimmed,
        defaultTestingApproach: approach,
      },
      {
        onSuccess: () => {
          handleClose();
        },
      },
    );
  };

  const handleDelete = (): void => {
    if (!suite) return;
    deleteSuite.mutate(
      { suiteId: suite.id, confirmCascade: true },
      {
        onSuccess: () => {
          handleClose();
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) handleClose();
      }}
    >
      <DialogContent data-testid="edit-suite-dialog" className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Edit suite</DialogTitle>
            <DialogDescription>
              Update suite details or remove this suite from the project.
            </DialogDescription>
          </DialogHeader>

          {confirmDelete ? (
            <div
              data-testid="delete-suite-confirm-pane"
              className="flex flex-col gap-3 rounded-md border border-red/30 bg-red/5 p-3"
            >
              <p className="text-[12.5px] font-medium text-red">
                Are you sure you want to delete &ldquo;{suite?.name}&rdquo;?
              </p>
              <p className="text-[12px] text-fg-3">
                This will soft-delete the suite and any test cases contained within it.
              </p>
              <div className="flex items-center justify-end gap-2 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid="delete-suite-cancel"
                  onClick={() => setConfirmDelete(false)}
                  disabled={deleteSuite.isPending}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  data-testid="delete-suite-confirm"
                  onClick={handleDelete}
                  disabled={deleteSuite.isPending}
                >
                  {deleteSuite.isPending ? "Deleting…" : "Delete suite"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-suite-name">Suite name</Label>
                <Input
                  id="edit-suite-name"
                  data-testid="edit-suite-name"
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                  }}
                  placeholder="e.g. Login flow"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="edit-suite-approach">Default testing approach</Label>
                <select
                  id="edit-suite-approach"
                  data-testid="edit-suite-approach"
                  value={approach}
                  onChange={(event) => {
                    setApproach(event.target.value as TestingApproach);
                  }}
                  className="h-9 rounded-md border border-border bg-bg-base px-3 text-[13px] text-fg-2 outline-none focus:border-accent"
                >
                  <option value="BLACK_BOX">Black-box — public behavior only</option>
                  <option value="GRAY_BOX">Gray-box — public behavior + internal context</option>
                  <option value="WHITE_BOX">White-box — internal tests and coverage</option>
                </select>
              </div>

              {suite && (
                <div className="pt-4 border-t border-border">
                  <VariablesTable scope="suite" suiteId={suite.id} />
                </div>
              )}
            </>
          )}

          {updateSuite.isError ? (
            <p data-testid="edit-suite-error" className="text-[12.5px] text-red">
              Couldn&apos;t update the suite. Please try again.
            </p>
          ) : null}

          {deleteSuite.isError ? (
            <p data-testid="delete-suite-error" className="text-[12.5px] text-red">
              Couldn&apos;t delete the suite. Please try again.
            </p>
          ) : null}

          {!confirmDelete ? (
            <DialogFooter className="flex items-center justify-between sm:justify-between">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                data-testid="delete-suite-trigger"
                className="text-red hover:bg-red/10 hover:text-red"
                onClick={() => setConfirmDelete(true)}
              >
                Delete suite
              </Button>
              <div className="flex items-center gap-2">
                <Button type="button" variant="outline" size="sm" onClick={handleClose}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="sm"
                  data-testid="edit-suite-submit"
                  disabled={name.trim().length === 0 || updateSuite.isPending}
                >
                  {updateSuite.isPending ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </DialogFooter>
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}

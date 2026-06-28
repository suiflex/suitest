import { useState } from "react";

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
import { useCreateWorkspace } from "@/hooks/use-workspaces";
import { ApiError } from "@/lib/api-client";

export interface CreateWorkspaceDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Create-workspace bootstrap (dogfood blocker #1). A freshly-registered or
 * invited user can have zero workspaces; this lets them make their first one —
 * becoming its OWNER — without leaving the UI. On success it switches to the
 * new workspace.
 */
export function CreateWorkspaceDialog({
  open,
  onClose,
}: CreateWorkspaceDialogProps): React.ReactElement {
  const [name, setName] = useState("");
  const createWorkspace = useCreateWorkspace();

  const reset = (): void => {
    setName("");
    createWorkspace.reset();
  };

  const close = (): void => {
    reset();
    onClose();
  };

  const handleSubmit = (event: React.FormEvent): void => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0) return;
    createWorkspace.mutate(
      { name: trimmed },
      {
        onSuccess: () => {
          close();
        },
      },
    );
  };

  const errorMessage = createWorkspace.isError
    ? createWorkspace.error instanceof ApiError && createWorkspace.error.status === 409
      ? "A workspace with that name already exists. Try another."
      : "Couldn't create the workspace. Please try again."
    : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent data-testid="create-workspace-dialog">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New workspace</DialogTitle>
            <DialogDescription>
              A workspace is your top-level tenant — it holds projects, suites, runs, and members.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="create-workspace-name">Workspace name</Label>
            <Input
              id="create-workspace-name"
              data-testid="create-workspace-name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
              placeholder="e.g. Acme QA"
            />
          </div>
          {errorMessage ? (
            <p data-testid="create-workspace-error" className="text-[12.5px] text-red">
              {errorMessage}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={close}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              data-testid="create-workspace-submit"
              disabled={name.trim().length === 0 || createWorkspace.isPending}
            >
              {createWorkspace.isPending ? "Creating…" : "Create workspace"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

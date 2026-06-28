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
import { useCreateProject } from "@/hooks/use-projects";
import { ApiError } from "@/lib/api-client";

export interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * First-project bootstrap (dogfood blocker #1). A fresh ZERO install has one
 * default workspace but no projects, and every project-scoped screen 422s
 * without an active project — so the user must be able to create the first one
 * entirely from the UI. On success the new project is made active.
 */
export function CreateProjectDialog({ open, onClose }: CreateProjectDialogProps): React.ReactElement {
  const [name, setName] = useState("");
  const createProject = useCreateProject();

  const reset = (): void => {
    setName("");
    createProject.reset();
  };

  const close = (): void => {
    reset();
    onClose();
  };

  const handleSubmit = (event: React.FormEvent): void => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0) return;
    createProject.mutate(
      { name: trimmed },
      {
        onSuccess: () => {
          close();
        },
      },
    );
  };

  const errorMessage = createProject.isError
    ? createProject.error instanceof ApiError && createProject.error.status === 409
      ? "A project with that name already exists. Try another."
      : "Couldn't create the project. Please try again."
    : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent data-testid="create-project-dialog">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Projects group your test suites. Name it after the app or service under test.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="create-project-name">Project name</Label>
            <Input
              id="create-project-name"
              data-testid="create-project-name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
              placeholder="e.g. Swag Labs"
            />
          </div>
          {errorMessage ? (
            <p data-testid="create-project-error" className="text-[12.5px] text-red">
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
              data-testid="create-project-submit"
              disabled={name.trim().length === 0 || createProject.isPending}
            >
              {createProject.isPending ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

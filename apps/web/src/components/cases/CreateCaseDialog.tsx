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
import { useCreateTestCase } from "@/hooks/use-test-cases";
import type { components } from "@/lib/api-types";

type Suite = components["schemas"]["SuitePublic"];

export interface CreateCaseDialogProps {
  open: boolean;
  onClose: () => void;
  /** Suites the case can be created under; the picker shows when there are ≥2. */
  suites: Suite[];
  /** Called with the new case's public id so the caller can open the editor. */
  onCreated?: (publicId: string) => void;
}

/**
 * Author a manual test case from scratch (bootstrap blocker #2). Before this,
 * a ZERO user could only get cases via the deterministic generators — the
 * "Write manually" empty-state actions were dead. Creates a MANUAL, step-less
 * case under the chosen suite; the caller opens it in the step editor.
 */
export function CreateCaseDialog({
  open,
  onClose,
  suites,
  onCreated,
}: CreateCaseDialogProps): React.ReactElement {
  const [name, setName] = useState("");
  // The user's explicit pick (empty = "use the default"). We derive the
  // effective suite from current props each render so a suite that lands AFTER
  // this dialog mounted (it's rendered persistently) still defaults correctly —
  // `useState(suites[0]?.id)` would freeze the first-render value.
  const [chosenSuiteId, setChosenSuiteId] = useState("");
  const suiteId = chosenSuiteId !== "" ? chosenSuiteId : (suites[0]?.id ?? "");
  const createCase = useCreateTestCase();

  const reset = (): void => {
    setName("");
    setChosenSuiteId("");
    createCase.reset();
  };

  const close = (): void => {
    reset();
    onClose();
  };

  const handleSubmit = (event: React.FormEvent): void => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0 || suiteId === "") return;
    createCase.mutate(
      { suiteId, name: trimmed },
      {
        onSuccess: (detail) => {
          onCreated?.(detail.public_id);
          close();
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent data-testid="create-case-dialog">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New test case</DialogTitle>
            <DialogDescription>
              Author a case by hand. You can add steps, expected results, and assertions next.
            </DialogDescription>
          </DialogHeader>
          {suites.length > 1 ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="create-case-suite">Suite</Label>
              <select
                id="create-case-suite"
                data-testid="create-case-suite"
                value={suiteId}
                onChange={(event) => {
                  setChosenSuiteId(event.target.value);
                }}
                className="h-9 rounded-md border border-border bg-bg-base px-2 text-[13px] text-fg-1 outline-none focus:border-accent"
              >
                {suites.map((suite) => (
                  <option key={suite.id} value={suite.id}>
                    {suite.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="create-case-name">Case name</Label>
            <Input
              id="create-case-name"
              data-testid="create-case-name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
              placeholder="e.g. Valid login"
            />
          </div>
          {createCase.isError ? (
            <p data-testid="create-case-error" className="text-[12.5px] text-red">
              Couldn&apos;t create the test case. Please try again.
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={close}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              data-testid="create-case-submit"
              disabled={name.trim().length === 0 || suiteId === "" || createCase.isPending}
            >
              {createCase.isPending ? "Creating…" : "Create case"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

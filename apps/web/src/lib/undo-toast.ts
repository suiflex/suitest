/**
 * undoToast — sonner-based 8s undo affordance for soft-delete operations.
 *
 * Usage:
 *   await undoToast({
 *     label: "Deleted TC-101",
 *     onUndo: () => api.post(`/test-cases/${id}/restore`),
 *   });
 *
 * Returns a promise that resolves to `true` if the user clicked Undo (and
 * onUndo ran successfully), or `false` if the toast auto-dismissed.
 *
 * ZERO-tier: no LLM, no capability gating. Pure UI affordance.
 */

import { toast } from "sonner";

export interface UndoToastOptions {
  /** Human-readable label, e.g. "Deleted TC-101" */
  label: string;
  /** Called when user clicks Undo. Throwing surfaces an error toast. */
  onUndo: () => Promise<unknown> | unknown;
  /** Override default 8s window */
  durationMs?: number;
  /** Optional success toast shown after Undo resolves */
  undoSuccessMessage?: string;
  /** Optional error message shown if Undo throws */
  undoErrorMessage?: string;
}

export function undoToast(opts: UndoToastOptions): Promise<boolean> {
  const duration = opts.durationMs ?? 8000;

  return new Promise<boolean>((resolve) => {
    let resolved = false;
    const finish = (undone: boolean): void => {
      if (resolved) return;
      resolved = true;
      resolve(undone);
    };

    const toastId = toast(opts.label, {
      duration,
      action: {
        label: "Undo",
        onClick: () => {
          void (async () => {
            try {
              await opts.onUndo();
              if (opts.undoSuccessMessage) {
                toast.success(opts.undoSuccessMessage);
              }
              finish(true);
            } catch (err) {
              const msg =
                opts.undoErrorMessage ??
                (err instanceof Error ? err.message : "Undo failed");
              toast.error(msg);
              finish(false);
            } finally {
              toast.dismiss(toastId);
            }
          })();
        },
      },
      onAutoClose: () => {
        finish(false);
      },
      onDismiss: () => {
        finish(false);
      },
    });
  });
}

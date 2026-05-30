/**
 * undo-toast.test.ts — unit suite for the M1d-23 undo affordance.
 *
 * Behavior checked:
 *   1. undoToast renders a sonner toast with the supplied label
 *   2. Clicking the Undo action runs onUndo and resolves to `true`
 *   3. Auto-dismiss resolves to `false` and does NOT call onUndo
 *   4. onUndo failure surfaces an error toast and resolves to `false`
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { undoToast } from "./undo-toast";

// We mock the entire sonner module so we can drive toast lifecycle synchronously.
vi.mock("sonner", () => {
  type ToastActionConfig = { label: string; onClick: () => void };
  type ToastOptions = {
    duration?: number;
    action?: ToastActionConfig;
    onAutoClose?: () => void;
    onDismiss?: () => void;
  };
  type ToastCall = { message: string; opts: ToastOptions; id: string };

  const calls: ToastCall[] = [];
  let nextId = 1;
  const successFn = vi.fn();
  const errorFn = vi.fn();
  const dismissFn = vi.fn();
  type ToastFn = ((message: string, opts?: ToastOptions) => string) & {
    success: typeof successFn;
    error: typeof errorFn;
    dismiss: typeof dismissFn;
    __calls: ToastCall[];
    __reset: () => void;
  };
  const toastFn = ((message: string, opts?: ToastOptions) => {
    const id = `toast_${nextId++}`;
    calls.push({ message, opts: opts ?? {}, id });
    return id;
  }) as ToastFn;
  toastFn.success = successFn;
  toastFn.error = errorFn;
  toastFn.dismiss = dismissFn;
  toastFn.__calls = calls;
  toastFn.__reset = () => {
    calls.length = 0;
    successFn.mockReset();
    errorFn.mockReset();
    dismissFn.mockReset();
    nextId = 1;
  };
  return { toast: toastFn };
});

import { toast } from "sonner";

type ToastCall = {
  message: string;
  opts: {
    duration?: number;
    action?: { label: string; onClick: () => void };
    onAutoClose?: () => void;
    onDismiss?: () => void;
  };
  id: string;
};

interface MockedToast {
  __calls: ToastCall[];
  __reset: () => void;
  success: ReturnType<typeof vi.fn>;
  error: ReturnType<typeof vi.fn>;
  dismiss: ReturnType<typeof vi.fn>;
}

const mocked = toast as unknown as MockedToast;

describe("undoToast", () => {
  beforeEach(() => {
    mocked.__reset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders a toast with the supplied label and default 8s duration", () => {
    void undoToast({ label: "Deleted TC-101", onUndo: vi.fn() });
    expect(mocked.__calls).toHaveLength(1);
    const call = mocked.__calls[0];
    expect(call?.message).toBe("Deleted TC-101");
    expect(call?.opts.duration).toBe(8000);
    expect(call?.opts.action?.label).toBe("Undo");
  });

  it("respects a custom duration override", () => {
    void undoToast({ label: "Deleted TC-102", onUndo: vi.fn(), durationMs: 3000 });
    expect(mocked.__calls[0]?.opts.duration).toBe(3000);
  });

  it("clicking Undo runs onUndo and resolves to true", async () => {
    const onUndo = vi.fn().mockResolvedValue(undefined);
    const promise = undoToast({
      label: "Deleted TC-103",
      onUndo,
      undoSuccessMessage: "Restored",
    });
    const call = mocked.__calls[0];
    expect(call?.opts.action?.onClick).toBeDefined();

    call?.opts.action?.onClick();
    const result = await promise;

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(mocked.success).toHaveBeenCalledWith("Restored");
    expect(mocked.dismiss).toHaveBeenCalledWith(call?.id);
    expect(result).toBe(true);
  });

  it("auto-close resolves to false and does NOT invoke onUndo", async () => {
    const onUndo = vi.fn();
    const promise = undoToast({ label: "Deleted TC-104", onUndo });
    const call = mocked.__calls[0];

    call?.opts.onAutoClose?.();
    const result = await promise;

    expect(onUndo).not.toHaveBeenCalled();
    expect(result).toBe(false);
  });

  it("manual dismiss resolves to false and does NOT invoke onUndo", async () => {
    const onUndo = vi.fn();
    const promise = undoToast({ label: "Deleted TC-105", onUndo });
    const call = mocked.__calls[0];

    call?.opts.onDismiss?.();
    const result = await promise;

    expect(onUndo).not.toHaveBeenCalled();
    expect(result).toBe(false);
  });

  it("onUndo failure surfaces error toast and resolves to false", async () => {
    const boom = new Error("restore boom");
    const onUndo = vi.fn().mockRejectedValue(boom);
    const promise = undoToast({
      label: "Deleted TC-106",
      onUndo,
      undoErrorMessage: "Failed to restore",
    });
    const call = mocked.__calls[0];

    call?.opts.action?.onClick();
    const result = await promise;

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(mocked.error).toHaveBeenCalledWith("Failed to restore");
    expect(result).toBe(false);
  });

  it("onUndo failure without explicit message falls back to error.message", async () => {
    const onUndo = vi.fn().mockRejectedValue(new Error("bespoke failure"));
    const promise = undoToast({ label: "Deleted TC-107", onUndo });
    const call = mocked.__calls[0];

    call?.opts.action?.onClick();
    const result = await promise;

    expect(mocked.error).toHaveBeenCalledWith("bespoke failure");
    expect(result).toBe(false);
  });

  it("resolves only once even when onAutoClose fires after onUndo resolved", async () => {
    const onUndo = vi.fn().mockResolvedValue(undefined);
    const promise = undoToast({ label: "Deleted TC-108", onUndo });
    const call = mocked.__calls[0];

    call?.opts.action?.onClick();
    const first = await promise;
    // Simulate the sonner runtime also firing onAutoClose after dismiss.
    call?.opts.onAutoClose?.();

    expect(first).toBe(true);
    expect(onUndo).toHaveBeenCalledTimes(1);
  });
});

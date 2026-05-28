import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useActiveWorkspace } from "@/stores/use-active-workspace";

const STORAGE_KEY = "suitest.activeWorkspaceId";

describe("useActiveWorkspace", () => {
  beforeEach(() => {
    useActiveWorkspace.getState().setWorkspaceId(null);
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem(STORAGE_KEY);
    }
  });

  afterEach(() => {
    useActiveWorkspace.getState().setWorkspaceId(null);
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem(STORAGE_KEY);
    }
  });

  it("starts with workspaceId === null", () => {
    expect(useActiveWorkspace.getState().workspaceId).toBeNull();
  });

  it("setWorkspaceId updates the store synchronously", () => {
    useActiveWorkspace.getState().setWorkspaceId("ws_abc");
    expect(useActiveWorkspace.getState().workspaceId).toBe("ws_abc");

    useActiveWorkspace.getState().setWorkspaceId("ws_def");
    expect(useActiveWorkspace.getState().workspaceId).toBe("ws_def");
  });

  it("setWorkspaceId(null) clears the selection", () => {
    useActiveWorkspace.getState().setWorkspaceId("ws_abc");
    expect(useActiveWorkspace.getState().workspaceId).toBe("ws_abc");
    useActiveWorkspace.getState().setWorkspaceId(null);
    expect(useActiveWorkspace.getState().workspaceId).toBeNull();
  });

  it("persists workspaceId to localStorage under the suitest namespace", () => {
    useActiveWorkspace.getState().setWorkspaceId("ws_persist");
    const raw = localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw ?? "{}") as {
      state?: { workspaceId?: string | null };
    };
    expect(parsed.state?.workspaceId).toBe("ws_persist");
  });
});

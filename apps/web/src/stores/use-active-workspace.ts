import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Active-workspace selector state.
 *
 * The backend `require_workspace_membership` dependency demands the
 * `X-Workspace-Id` header on every authenticated request. We keep the active
 * workspace id in a tiny persisted Zustand slice so:
 *
 *   1. `apps/web/src/lib/api-client.ts` can read it synchronously inside the
 *      axios request interceptor (no React state in the hot path).
 *   2. `apps/web/src/routes/_app.tsx#beforeLoad` can seed it the first time
 *      the user authenticates (auto-pick the first membership).
 *   3. The Sidebar workspace picker can display the active workspace name
 *      using the real memberships returned by `/auth/me`.
 *
 * Persistence key is intentionally namespaced (`suitest.*`) so multiple
 * suitest instances on the same origin don't collide.
 */
interface ActiveWorkspaceState {
  workspaceId: string | null;
  setWorkspaceId: (id: string | null) => void;
}

export const useActiveWorkspace = create<ActiveWorkspaceState>()(
  persist(
    (set) => ({
      workspaceId: null,
      setWorkspaceId: (id) => set({ workspaceId: id }),
    }),
    { name: "suitest.activeWorkspaceId" },
  ),
);

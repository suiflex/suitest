import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Active-project selector state.
 *
 * Every project-scoped backend endpoint (`/analytics/*`, `/suites`, `/runs`,
 * `/traceability/matrix`, ...) requires a `projectId` query param and returns
 * 422 without it. We keep the active project id in a tiny persisted Zustand
 * slice — mirroring `use-active-workspace` — so:
 *
 *   1. Data hooks (`use-analytics`, `use-dashboard`, `use-runs`, ...) read it
 *      synchronously and inject it into params + query keys.
 *   2. `routes/_app.tsx#beforeLoad` seeds it (and reconciles a stale id after
 *      a reseed or a workspace switch) against the real `/projects` list.
 *
 * Projects are workspace-scoped, so a persisted id may belong to a different
 * workspace; callers MUST reconcile it against the active workspace's project
 * list rather than trusting the persisted value blindly.
 */
interface ActiveProjectState {
  projectId: string | null;
  setProjectId: (id: string | null) => void;
}

export const useActiveProject = create<ActiveProjectState>()(
  persist(
    (set) => ({
      projectId: null,
      setProjectId: (id) => set({ projectId: id }),
    }),
    { name: "suitest.activeProjectId" },
  ),
);

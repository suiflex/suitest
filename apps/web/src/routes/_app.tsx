import { Outlet, createFileRoute, isRedirect, redirect } from "@tanstack/react-router";

import { AiPanel } from "@/components/shell/AiPanel";
import { Sidebar } from "@/components/shell/Sidebar";
import { Topbar } from "@/components/shell/Topbar";
import { useCurrentUser, type CurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api-client";
import { useActiveProject } from "@/stores/use-active-project";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";
import type { components } from "@/lib/api-types";

type ProjectsPage = components["schemas"]["Page_ProjectPublic_"];

/**
 * Pathless protected layout. Every authenticated route nests under this so
 * the `beforeLoad` guard runs once per navigation. On 401 we redirect to
 * `/login?next=<original-path>` so the user lands back where they started
 * after authenticating.
 *
 * NOTE: `api-client` already redirects on 401 in its response interceptor —
 * this guard is belt-and-suspenders, and also ensures router state stays in
 * sync (the interceptor mutates `window.location` outside React).
 *
 * The guard also performs two boot-time side effects:
 *
 *   1. Seeds the active workspace from the first membership when no
 *      selection is persisted — this is what makes the `X-Workspace-Id`
 *      header non-empty on subsequent requests.
 *
 *   2. Awaits the capabilities fetch so descendant surfaces (TierBadge,
 *      Gated, AiPanel rail) render with the real tier on first paint
 *      instead of flashing ZERO and snapping to CLOUD.
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    try {
      const me = await context.queryClient.ensureQueryData<CurrentUser>({
        queryKey: ["auth", "me"],
        queryFn: async () => (await api.get<CurrentUser>("/auth/me")).data,
      });
      // Force a password change before anything else when an admin reset set
      // the marker. Done in `beforeLoad` (not a component effect) so there's no
      // render flash and no redirect loop — `/settings` is excluded.
      if (me.must_change_password && location.pathname !== "/settings") {
        throw redirect({ to: "/settings", search: { force_password: "1" } });
      }
      // Seed the active workspace when the user hasn't picked one yet, OR when
      // the persisted id is stale (e.g. the DB was reseeded and workspace ids
      // regenerated). Without this reconciliation the api-client keeps sending
      // a dead `X-Workspace-Id`, and every authed endpoint returns 403
      // "user is not a member of the requested workspace".
      const ws = useActiveWorkspace.getState();
      const validIds = new Set(me.memberships.map((m) => m.workspace_id));
      if ((ws.workspaceId === null || !validIds.has(ws.workspaceId)) && me.memberships.length > 0) {
        const first = me.memberships[0];
        if (first) {
          ws.setWorkspaceId(first.workspace_id);
        }
      }
      // Seed / reconcile the active project. Every project-scoped endpoint
      // (`/analytics/*`, `/suites`, `/runs`, `/traceability/matrix`) returns
      // 422 without a `projectId`, so the active project MUST be resolved
      // before the shell renders. The persisted id may be null (first login),
      // stale (DB reseed), or belong to a different workspace, so we always
      // reconcile it against the freshly-fetched project list.
      const projects = await context.queryClient.ensureQueryData<ProjectsPage>({
        queryKey: ["projects"],
        queryFn: async () => (await api.get<ProjectsPage>("/projects")).data,
      });
      const proj = useActiveProject.getState();
      const validProjectIds = new Set(projects.items.map((p) => p.id));
      if (
        (proj.projectId === null || !validProjectIds.has(proj.projectId)) &&
        projects.items.length > 0
      ) {
        const firstProject = projects.items[0];
        if (firstProject) {
          proj.setProjectId(firstProject.id);
        }
      }
      // Capabilities boot — block render until we know the tier so the
      // shell doesn't flash ZERO → CLOUD on first paint.
      if (useCapabilities.getState().capabilities === null) {
        await useCapabilities.getState().fetch();
      }
    } catch (err) {
      // A deliberate redirect (e.g. the must_change_password guard above) must
      // propagate unchanged — only auth failures fall through to /login.
      if (isRedirect(err)) {
        throw err;
      }
      throw redirect({
        to: "/login",
        search: { next: location.pathname },
      });
    }
  },
  component: AppLayout,
});

/**
 * Three-column shell:
 *   [Sidebar 224px] [Topbar + Outlet] [AiPanel 380px]
 *
 * The right rail collapses in ZERO tier (no LLM features) and on viewports
 * narrower than 1280px (Tailwind `xl:`). M1b ships the desktop layout only;
 * the responsive sheet/drawer fallback lands with the real agent in M3.
 */
function AppLayout(): React.ReactElement {
  const tier = useCapabilities((s) => s.capabilities?.tier);
  const cols =
    tier === "ZERO"
      ? "grid-cols-[224px_1fr]"
      : "grid-cols-[224px_1fr] xl:grid-cols-[224px_1fr_380px]";

  const { data: user } = useCurrentUser();
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const memberships = user.memberships;
  const activeMembership =
    memberships.find((m) => m.workspace_id === activeWorkspaceId) ?? memberships[0];
  const workspaceName = activeMembership?.workspace.name;
  const workspaces = memberships.map((m) => ({
    id: m.workspace.id,
    name: m.workspace.name,
  }));
  const userName = user.name ?? user.email.split("@")[0] ?? "Account";
  const userRole = activeMembership?.role;

  return (
    <div className={`grid ${cols} min-h-screen`} data-testid="app-shell">
      <Sidebar
        {...(workspaceName !== undefined ? { workspaceName } : {})}
        userName={userName}
        {...(userRole !== undefined ? { userRole } : {})}
        {...(workspaces.length > 0 ? { workspaces } : {})}
        isSuperuser={user.is_superuser === true}
      />
      <div className="flex min-w-0 flex-col">
        <Topbar />
        <main className="flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
      {tier !== "ZERO" ? <AiPanel /> : null}
    </div>
  );
}

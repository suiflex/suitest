import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";

import { AiPanel } from "@/components/shell/AiPanel";
import { Sidebar } from "@/components/shell/Sidebar";
import { Topbar } from "@/components/shell/Topbar";
import type { CurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api-client";
import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Pathless protected layout. Every authenticated route nests under this so
 * the `beforeLoad` guard runs once per navigation. On 401 we redirect to
 * `/login?next=<original-path>` so the user lands back where they started
 * after authenticating.
 *
 * NOTE: `api-client` already redirects on 401 in its response interceptor —
 * this guard is belt-and-suspenders, and also ensures router state stays in
 * sync (the interceptor mutates `window.location` outside React).
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData({
        queryKey: ["auth", "me"],
        queryFn: async () => (await api.get<CurrentUser>("/auth/me")).data,
      });
    } catch {
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

  return (
    <div className={`grid ${cols} min-h-screen`} data-testid="app-shell">
      <Sidebar />
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

import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";

import { TierBadge } from "@/components/tier-badge";
import { api } from "@/lib/api-client";
import type { CurrentUser } from "@/hooks/use-current-user";

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

function AppLayout(): React.ReactElement {
  // M1b: brand header + outlet only. Task 5 will replace this with the real
  // Sidebar / Topbar / AiPanel shell.
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <h1 className="font-mono text-lg font-semibold tracking-tight">
          suitest
        </h1>
        <TierBadge />
      </header>
      <main className="flex-1 px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

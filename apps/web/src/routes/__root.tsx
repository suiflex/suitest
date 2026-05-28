import type { QueryClient } from "@tanstack/react-query";
import { Outlet, createRootRouteWithContext } from "@tanstack/react-router";
import { Suspense, useEffect } from "react";

import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Router context contract. `main.tsx` provides the QueryClient; `_app.tsx`
 * (and other route loaders) read it from `beforeLoad`/`loader` arguments.
 */
export interface RouterContext {
  queryClient: QueryClient;
}

/**
 * Augment TanStack's `StaticDataRouteOption` so routes can declare typed
 * metadata (e.g. `title` for Topbar breadcrumbs).
 */
declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** Display label used by Topbar breadcrumbs. */
    title?: string;
  }
}

function RootLayout(): React.ReactElement {
  // Boot capabilities once on root mount so `<Gated>` / `<TierBadge>` have
  // data ready before any feature surface renders. Task 5 will swap this for
  // a Suspense `<CapabilityBoot>` when the shell is wired.
  const fetch = useCapabilities((s) => s.fetch);
  useEffect(() => {
    void fetch();
  }, [fetch]);

  return (
    <Suspense fallback={<RootFallback />}>
      <Outlet />
    </Suspense>
  );
}

function RootFallback(): React.ReactElement {
  return (
    <div className="flex min-h-screen items-center justify-center text-fg-3">
      <span className="font-mono text-xs">Loading…</span>
    </div>
  );
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});

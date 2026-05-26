import { Outlet, createRootRoute } from "@tanstack/react-router";
import { useEffect } from "react";

import { TierBadge } from "@/components/tier-badge";
import { useCapabilities } from "@/stores/use-capabilities";

function RootLayout(): React.ReactElement {
  const fetch = useCapabilities((s) => s.fetch);
  useEffect(() => {
    void fetch();
  }, [fetch]);

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <h1 className="font-mono text-lg font-semibold tracking-tight">Suitest</h1>
        <TierBadge />
      </header>
      <main className="flex-1 px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

export const Route = createRootRoute({ component: RootLayout });

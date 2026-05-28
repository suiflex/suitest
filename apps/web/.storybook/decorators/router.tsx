import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import type { Decorator } from "@storybook/react-vite";

/**
 * Wraps every story in a memory-history TanStack Router so components that
 * call `useMatches` / `useNavigate` or render `<Link>` (Sidebar, Topbar)
 * don't crash when opened in Storybook.
 *
 * The route tree mirrors the production sidebar destinations + a few extras
 * the Topbar breadcrumb selector reads `staticData.title` from, so the
 * shell renders with realistic crumbs instead of an empty match list.
 *
 * Each story instantiates its own router (shared QueryClient) so navigation
 * inside one story can't leak into another.
 */
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const NAV_TARGETS: ReadonlyArray<{ path: string; title: string }> = [
  { path: "/dashboard", title: "Dashboard" },
  { path: "/cases", title: "Test Cases" },
  { path: "/runs", title: "Test Runs" },
  { path: "/defects", title: "Defects" },
  { path: "/analytics", title: "Analytics" },
  { path: "/trace", title: "Traceability" },
  { path: "/integrations", title: "Integrations" },
  { path: "/docs", title: "Documents" },
  { path: "/inbox", title: "Inbox" },
  { path: "/settings", title: "Settings" },
];

const rootRoute = createRootRoute({ component: Outlet });
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Outlet,
});
const navRoutes = NAV_TARGETS.map((t) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path: t.path,
    component: Outlet,
    staticData: { title: t.title },
  }),
);
const routeTree = rootRoute.addChildren([indexRoute, ...navRoutes]);

export const withRouter: Decorator = (Story) => {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/dashboard"] }),
    context: { queryClient },
    defaultComponent: () => <Story />,
  });
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
};

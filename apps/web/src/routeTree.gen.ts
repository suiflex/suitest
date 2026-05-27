// Hand-written for M0 — TanStack Router CLI will replace this in M1.
import { Route as RootRoute } from "./routes/__root";
import { Route as IndexRoute } from "./routes/index";
import { Route as LoginRoute } from "./routes/login";
import { Route as DashboardRoute } from "./routes/dashboard";

declare module "@tanstack/react-router" {
  interface FileRoutesByPath {
    "/": {
      id: "/";
      path: "/";
      fullPath: "/";
      preLoaderRoute: typeof IndexRoute;
      parentRoute: typeof RootRoute;
    };
    "/login": {
      id: "/login";
      path: "/login";
      fullPath: "/login";
      preLoaderRoute: typeof LoginRoute;
      parentRoute: typeof RootRoute;
    };
    "/dashboard": {
      id: "/dashboard";
      path: "/dashboard";
      fullPath: "/dashboard";
      preLoaderRoute: typeof DashboardRoute;
      parentRoute: typeof RootRoute;
    };
  }
}

export const routeTree = RootRoute.addChildren([IndexRoute, LoginRoute, DashboardRoute]);

import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * Root index just bounces into the dashboard. The `_app` guard handles auth;
 * unauthenticated users will be redirected to /login from there.
 */
export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/dashboard" });
  },
});

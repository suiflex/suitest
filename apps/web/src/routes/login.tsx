import { createFileRoute } from "@tanstack/react-router";

interface LoginSearch {
  next?: string;
}

interface AuthorizeResponse {
  authorization_url: string;
}

/**
 * The FastAPI-Users Google OAuth flow returns JSON `{authorization_url}` from
 * `/auth/google/authorize` (it does not 302 directly). We fetch that, then
 * full-redirect the browser. After Google's callback the API sets the
 * session cookie and redirects to `next` (default `/dashboard`).
 *
 * The backend mounts the OAuth router at the application root (NOT under
 * `/api/v1`) — confirmed in `packages/shared/openapi.json` and
 * `apps/api/src/suitest_api/auth/router.py`. The Vite dev proxy forwards
 * `/auth/*` to the backend (see `apps/web/vite.config.ts`).
 */
function Login(): React.ReactElement {
  const search = Route.useSearch();
  const nextPath = search.next ?? "/dashboard";

  const onGoogle = async (): Promise<void> => {
    const url = `/auth/google/authorize?next=${encodeURIComponent(nextPath)}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) {
      // Server didn't return the authorize URL — surface a friendly hint.
      console.error("Google authorize endpoint returned", res.status);
      return;
    }
    const data = (await res.json()) as AuthorizeResponse;
    window.location.assign(data.authorization_url);
  };

  return (
    <section className="mx-auto max-w-md space-y-6 pt-16 text-center">
      <h2 className="font-mono text-2xl font-semibold tracking-tight">
        sui<span className="text-accent">test</span>
      </h2>
      <p className="text-fg-3">
        Sign in with Google to continue. You will be redirected to{" "}
        <code className="font-mono text-fg-1">{nextPath}</code> after sign-in.
      </p>
      <button
        type="button"
        onClick={() => {
          void onGoogle();
        }}
        className="inline-flex items-center justify-center rounded-md border border-border bg-elev-1 px-4 py-2 font-medium text-fg-1 hover:bg-elev-2"
      >
        Sign in with Google
      </button>
    </section>
  );
}

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => {
    const next = search["next"];
    return typeof next === "string" ? { next } : {};
  },
  component: Login,
});

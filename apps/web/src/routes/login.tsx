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
 * Plan 4.4 mentions `window.location.assign('/api/v1/...')` directly, but the
 * current M1a backend returns JSON; using a direct assign would render the
 * raw JSON to the user. Documented discrepancy — revisit once the API
 * switches to a 302 response.
 */
function Login(): React.ReactElement {
  const search = Route.useSearch();
  const nextPath = search.next ?? "/dashboard";

  const onGoogle = async (): Promise<void> => {
    const url = `/api/v1/auth/google/authorize?next=${encodeURIComponent(nextPath)}`;
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

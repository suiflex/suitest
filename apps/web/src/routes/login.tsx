import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useCapabilities } from "@/stores/use-capabilities";

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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Login is a public route (outside the `_app` guard) so capabilities aren't
  // necessarily loaded yet. Fetch them once so the Google button's visibility
  // reflects the real server config instead of being hardcoded.
  const capabilities = useCapabilities((s) => s.capabilities);
  useEffect(() => {
    if (useCapabilities.getState().capabilities === null) {
      void useCapabilities.getState().fetch();
    }
  }, []);
  const googleEnabled = capabilities?.auth?.google_oauth_enabled === true;

  const onPasswordLogin = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);

    try {
      const res = await fetch("/auth/cookie/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!res.ok) {
        throw new Error("bad_credentials");
      }
      window.location.assign(nextPath);
    } catch {
      setError("Email or password did not match an active Suitest account.");
    } finally {
      setSubmitting(false);
    }
  };

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
    <section className="mx-auto max-w-md space-y-6 pt-16">
      <div className="space-y-3 text-center">
        <img src="/logo.svg" alt="Suitest" className="mx-auto h-12 w-12 rounded-xl" />
        <h2 className="font-mono text-2xl font-semibold tracking-tight">
          sui<span className="text-accent">test</span>
        </h2>
        <p className="text-[13px] text-fg-3">
          Sign in to continue to{" "}
          <code className="font-mono text-[12px] text-fg-1">{nextPath}</code>.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          void onPasswordLogin(event);
        }}
        className="space-y-4 rounded-lg border border-border bg-elev-1 p-5 text-left"
      >
        <div className="space-y-2">
          <label htmlFor="email" className="text-[12.5px] font-medium text-fg-1">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none placeholder:text-fg-5 focus:border-accent"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="password" className="text-[12.5px] font-medium text-fg-1">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none placeholder:text-fg-5 focus:border-accent"
          />
        </div>

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
          >
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex w-full items-center justify-center rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>

      {googleEnabled ? (
        <div className="space-y-3 text-center">
          <div className="flex items-center gap-3 text-[11px] uppercase tracking-[0.07em] text-fg-4">
            <span className="h-px flex-1 bg-border" />
            <span>Secondary</span>
            <span className="h-px flex-1 bg-border" />
          </div>
          <button
            type="button"
            onClick={() => {
              void onGoogle();
            }}
            className="inline-flex items-center justify-center rounded-md border border-border bg-elev-1 px-4 py-2 font-medium text-fg-1 hover:bg-elev-2"
          >
            Sign in with Google
          </button>
        </div>
      ) : null}
      <p className="pt-4 text-center text-[11px] text-fg-5">
        © 2026 Suitest contributors · Apache-2.0 · open source
      </p>
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

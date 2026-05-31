import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  acceptInvitation,
  validateInvitation,
  type InvitationValidation,
} from "@/lib/api-client";

interface AcceptInviteSearch {
  token?: string;
}

function messageForInviteError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "INVITATION_EXPIRED" || error.status === 410) {
      return "This invitation link has expired.";
    }
    if (error.code === "INVITATION_REVOKED") {
      return "This invitation link was revoked.";
    }
    if (error.code === "INVITATION_ACCEPTED") {
      return "This invitation link was already accepted.";
    }
  }
  return "This invitation link is invalid.";
}

function AcceptInvite(): React.ReactElement {
  const search = Route.useSearch();
  const token = search.token ?? "";
  const [invite, setInvite] = useState<InvitationValidation | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load(): Promise<void> {
      if (!token) {
        setError("This invitation link is invalid.");
        setLoading(false);
        return;
      }

      try {
        const data = await validateInvitation(token);
        if (active) {
          setInvite(data);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(messageForInviteError(err));
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      active = false;
    };
  }, [token]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await acceptInvitation({ token, name, password });
      window.location.assign("/dashboard");
    } catch (err) {
      setError(messageForInviteError(err));
      setSubmitting(false);
    }
  };

  return (
    <section className="mx-auto max-w-lg space-y-6 pt-16">
      <div className="space-y-2 text-center">
        <h2 className="font-mono text-2xl font-semibold tracking-tight">
          sui<span className="text-accent">test</span>
        </h2>
        <p className="text-[13px] text-fg-3">Accept your workspace invitation.</p>
      </div>

      <div className="rounded-lg border border-border bg-elev-1 p-5">
        {loading ? <p className="font-mono text-[12px] text-fg-3">Checking invitation...</p> : null}

        {!loading && error && !invite ? (
          <div role="alert" className="space-y-2">
            <h1 className="text-[18px] font-semibold text-fg-1">Invitation unavailable</h1>
            <p className="text-[13px] text-red">{error}</p>
          </div>
        ) : null}

        {!loading && invite ? (
          <div className="space-y-5">
            <dl className="grid gap-3 rounded-md border border-border bg-bg-base p-4 text-[13px]">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-fg-4">Workspace</dt>
                <dd className="font-medium text-fg-1">{invite.workspace_name}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-fg-4">Email</dt>
                <dd className="font-medium text-fg-1">{invite.email}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-fg-4">Role</dt>
                <dd className="font-mono text-[12px] text-fg-1">{invite.role}</dd>
              </div>
            </dl>

            <form
              onSubmit={(event) => {
                void onSubmit(event);
              }}
              className="space-y-4"
            >
              <div className="space-y-2">
                <label htmlFor="name" className="text-[12.5px] font-medium text-fg-1">
                  Name
                </label>
                <input
                  id="name"
                  name="name"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none placeholder:text-fg-5 focus:border-accent"
                />
              </div>

              <div className="space-y-2">
                <label htmlFor="invite-password" className="text-[12.5px] font-medium text-fg-1">
                  Password
                </label>
                <input
                  id="invite-password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={8}
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
                {submitting ? "Creating account..." : "Create account"}
              </button>
            </form>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export const Route = createFileRoute("/accept-invite")({
  validateSearch: (search: Record<string, unknown>): AcceptInviteSearch => {
    const token = search["token"];
    return typeof token === "string" ? { token } : {};
  },
  component: AcceptInvite,
});

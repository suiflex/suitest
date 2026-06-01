import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { AutomationPanel } from "@/components/settings/AutomationPanel";
import { CostPanel } from "@/components/settings/CostPanel";
import { LlmSettingsPanel } from "@/components/settings/LlmSettingsPanel";
import { MembersPanel } from "@/components/settings/MembersPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ApiError, changeOwnPassword } from "@/lib/api-client";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

interface SettingsSearch {
  /** Set by the `_app` must_change_password guard to force the Account tab. */
  force_password?: string;
}

/** Roles allowed to see the Members tab (OWNER + ADMIN). */
function canSeeMembers(role: string | undefined): boolean {
  return role === "OWNER" || role === "ADMIN";
}

function SettingsScreen(): React.ReactElement {
  const search = Route.useSearch();
  const { data: user } = useCurrentUser();
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);

  const activeMembership =
    user.memberships.find((m) => m.workspace_id === activeWorkspaceId) ?? user.memberships[0];
  const role = activeMembership?.role;
  const workspaceId = activeMembership?.workspace_id ?? activeWorkspaceId;

  const forcePassword = search.force_password === "1" || user.must_change_password === true;
  const showMembers = canSeeMembers(role);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-[20px] font-semibold text-fg-1">Settings</h1>
        <p className="text-[13px] text-fg-3">Manage your account and workspace members.</p>
      </div>

      {forcePassword ? (
        <div
          role="alert"
          className="rounded-md border border-amber/30 bg-amber/10 px-4 py-3 text-[13px] text-amber"
          data-testid="force-password-banner"
        >
          You must change your password before continuing.
        </div>
      ) : null}

      <Tabs defaultValue="account">
        <TabsList>
          <TabsTrigger value="account">Account</TabsTrigger>
          {showMembers ? <TabsTrigger value="members">Members</TabsTrigger> : null}
          {workspaceId ? <TabsTrigger value="llm">LLM</TabsTrigger> : null}
          {workspaceId ? <TabsTrigger value="automation">Automation</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="account" className="pt-4">
          <AccountTab />
        </TabsContent>

        {showMembers && workspaceId ? (
          <TabsContent value="members" className="pt-4">
            <MembersPanel workspaceId={workspaceId} currentRole={role} />
          </TabsContent>
        ) : null}

        {workspaceId ? (
          <TabsContent value="llm" className="space-y-8 pt-4">
            <LlmSettingsPanel workspaceId={workspaceId} canWrite={showMembers} />
            <CostPanel workspaceId={workspaceId} />
          </TabsContent>
        ) : null}

        {workspaceId ? (
          <TabsContent value="automation" className="pt-4">
            <AutomationPanel workspaceId={workspaceId} canWrite={showMembers} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

function AccountTab(): React.ReactElement {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSuccess(false);

    if (next.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      setError("New password and confirmation do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await changeOwnPassword({ current_password: current, new_password: next });
      // Refetch the current user so `must_change_password` clears and the
      // `_app` guard stops forcing the user onto this screen.
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      setCurrent("");
      setNext("");
      setConfirm("");
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 401)) {
        setError("Your current password is incorrect.");
      } else {
        setError("Could not change your password. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="max-w-md space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5">
      <h2 className="text-[15px] font-semibold text-fg-1">Change password</h2>
      <form
        onSubmit={(event) => {
          void onSubmit(event);
        }}
        className="space-y-4"
      >
        <div className="space-y-2">
          <label htmlFor="current-password" className="text-[12.5px] font-medium text-fg-1">
            Current password
          </label>
          <input
            id="current-password"
            name="current_password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="new-password" className="text-[12.5px] font-medium text-fg-1">
            New password
          </label>
          <input
            id="new-password"
            name="new_password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="confirm-password" className="text-[12.5px] font-medium text-fg-1">
            Confirm new password
          </label>
          <input
            id="confirm-password"
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
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

        {success ? (
          <p
            role="status"
            className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-[12.5px] text-accent"
          >
            Password changed.
          </p>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex h-9 w-full items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          data-testid="change-password-submit"
        >
          {submitting ? "Changing…" : "Change password"}
        </button>
      </form>
    </section>
  );
}

export const Route = createFileRoute("/_app/settings")({
  validateSearch: (search: Record<string, unknown>): SettingsSearch => {
    const force = search["force_password"];
    return typeof force === "string" ? { force_password: force } : {};
  },
  component: SettingsScreen,
});

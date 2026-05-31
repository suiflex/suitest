import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";
import { useState } from "react";

import { CopyButton } from "@/components/shared/CopyButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type CurrentUser } from "@/hooks/use-current-user";
import {
  adminResetPassword,
  api,
  listMembers,
  listPasswordResetRequests,
  type WorkspaceMemberPublic,
} from "@/lib/api-client";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

function AdminScreen(): React.ReactElement {
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);

  // No global "all users" endpoint exists in the M1e API; the only available
  // roster is the active workspace's members. A reset targets `user_id`, which
  // `WorkspaceMemberPublic` provides.
  const usersQuery = useQuery({
    queryKey: ["admin", "members", activeWorkspaceId],
    queryFn: () => listMembers(activeWorkspaceId ?? ""),
    enabled: activeWorkspaceId !== null,
  });

  const resetRequestsQuery = useQuery({
    queryKey: ["admin", "password-reset-requests"],
    queryFn: () => listPasswordResetRequests(),
  });

  const [resetUser, setResetUser] = useState<WorkspaceMemberPublic | null>(null);
  const [tempPassword, setTempPassword] = useState<string | null>(null);

  const resetMutation = useMutation({
    mutationFn: (userId: string) => adminResetPassword(userId),
    onSuccess: (res) => {
      setTempPassword(res.temporaryPassword);
    },
  });

  const onReset = (member: WorkspaceMemberPublic): void => {
    setResetUser(member);
    setTempPassword(null);
    resetMutation.mutate(member.user_id);
  };

  const requests = resetRequestsQuery.data;

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="space-y-1">
        <h1 className="text-[20px] font-semibold text-fg-1">Admin</h1>
        <p className="text-[13px] text-fg-3">Super-admin user and recovery tools.</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-[15px] font-semibold text-fg-1">Users</h2>
        {usersQuery.isError ? (
          <p
            role="alert"
            className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
          >
            Could not load users. Try again.
          </p>
        ) : (usersQuery.data ?? []).length === 0 ? (
          <p className="text-[13px] text-fg-4">No users to show.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-bg-elev-2 text-[11px] uppercase tracking-[0.07em] text-fg-4">
                <tr>
                  <th className="px-3 py-2 font-medium">User</th>
                  <th className="px-3 py-2 font-medium">Email</th>
                  <th className="px-3 py-2 font-medium">Role</th>
                  <th className="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(usersQuery.data ?? []).map((u) => (
                  <tr key={u.user_id} className="border-t border-border" data-testid="user-row">
                    <td className="px-3 py-2 text-fg-1">{u.name}</td>
                    <td className="px-3 py-2 text-fg-3">{u.email}</td>
                    <td className="px-3 py-2 font-mono text-[12px] text-fg-1">{u.role}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        disabled={resetMutation.isPending && resetUser?.user_id === u.user_id}
                        onClick={() => onReset(u)}
                        className="rounded-md px-2 py-1 text-[12px] font-medium text-fg-1 hover:bg-bg-elev-2 disabled:opacity-50"
                        data-testid={`reset-${u.user_id}`}
                      >
                        Reset password
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-[15px] font-semibold text-fg-1">Password reset requests</h2>
        {resetRequestsQuery.isError ? (
          <p
            role="alert"
            className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
          >
            Could not load reset requests. Try again.
          </p>
        ) : requests && !requests.encryptionConfigured ? (
          <p
            className="rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-[12.5px] text-fg-4"
            data-testid="encryption-not-configured"
          >
            Encryption not configured — reset links unavailable.
          </p>
        ) : (requests?.items ?? []).length === 0 ? (
          <p className="text-[13px] text-fg-4">No pending reset requests.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-bg-elev-2 text-[11px] uppercase tracking-[0.07em] text-fg-4">
                <tr>
                  <th className="px-3 py-2 font-medium">Email</th>
                  <th className="px-3 py-2 font-medium">Requested</th>
                  <th className="px-3 py-2 font-medium">Reset link</th>
                </tr>
              </thead>
              <tbody>
                {(requests?.items ?? []).map((req) => (
                  <tr key={req.id} className="border-t border-border" data-testid="reset-request-row">
                    <td className="px-3 py-2 text-fg-1">{req.email}</td>
                    <td className="px-3 py-2 text-fg-3">
                      {new Date(req.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2">
                      {req.resetLink ? (
                        <div className="flex items-center gap-2">
                          <code className="max-w-[260px] flex-1 truncate rounded-md border border-border bg-bg-base px-2 py-1 font-mono text-[11px] text-fg-1">
                            {req.resetLink}
                          </code>
                          <CopyButton value={req.resetLink} label="Copy" />
                        </div>
                      ) : (
                        <span className="text-fg-4">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Dialog
        open={resetUser !== null}
        onOpenChange={(open) => {
          if (!open) {
            setResetUser(null);
            setTempPassword(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Temporary password</DialogTitle>
            <DialogDescription>
              {resetUser ? `One-time password for ${resetUser.email}.` : ""}
            </DialogDescription>
          </DialogHeader>

          {resetMutation.isPending ? (
            <p className="text-[13px] text-fg-3">Generating…</p>
          ) : resetMutation.isError ? (
            <p
              role="alert"
              className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
            >
              Could not reset the password. Please try again.
            </p>
          ) : tempPassword ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <code
                  className="flex-1 truncate rounded-md border border-border bg-bg-base px-3 py-2 font-mono text-[13px] text-fg-1"
                  data-testid="temp-password"
                >
                  {tempPassword}
                </code>
                <CopyButton value={tempPassword} label="Copy" />
              </div>
              <p className="text-[12px] text-amber">
                This password will not be shown again. Copy it now and share it securely.
              </p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export const Route = createFileRoute("/_app/admin")({
  beforeLoad: async ({ context }) => {
    // Super-admin only. The `_app` parent guard already authenticated the user
    // and cached `["auth","me"]`; read it back and bounce non-superusers.
    const cached = context.queryClient.getQueryData<CurrentUser>(["auth", "me"]);
    const user =
      cached ??
      (await context.queryClient.ensureQueryData<CurrentUser>({
        queryKey: ["auth", "me"],
        queryFn: async () => (await api.get<CurrentUser>("/auth/me")).data,
      }));
    if (user.is_superuser !== true) {
      throw redirect({ to: "/dashboard" });
    }
  },
  component: AdminScreen,
});

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { CopyButton } from "@/components/shared/CopyButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  createInvitation,
  type InvitationOut,
  type InvitationStatus,
  invitationStatus,
  listInvitations,
  listMembers,
  resendInvitation,
  revokeInvitation,
  type Role,
} from "@/lib/api-client";

/** Invite creation is limited to ADMIN/QA/VIEWER — OWNER stays a separate action. */
const INVITE_ROLES: Role[] = ["ADMIN", "QA", "VIEWER"];

/** Roles allowed to manage invitations (OWNER + ADMIN). */
function canManageInvites(role: string | undefined): boolean {
  return role === "OWNER" || role === "ADMIN";
}

const STATUS_STYLE: Record<InvitationStatus, string> = {
  pending: "text-amber",
  accepted: "text-accent",
  revoked: "text-fg-4",
  expired: "text-red",
};

interface MembersPanelProps {
  workspaceId: string;
  /** Current user's role in this workspace; gates the Invite affordances. */
  currentRole: string | undefined;
}

export function MembersPanel({ workspaceId, currentRole }: MembersPanelProps): React.ReactElement {
  const queryClient = useQueryClient();
  const isAdmin = canManageInvites(currentRole);

  const membersQuery = useQuery({
    queryKey: ["workspace", workspaceId, "members"],
    queryFn: () => listMembers(workspaceId),
  });

  const invitesQuery = useQuery({
    queryKey: ["workspace", workspaceId, "invitations"],
    queryFn: () => listInvitations(workspaceId),
    enabled: isAdmin,
  });

  const [inviteOpen, setInviteOpen] = useState(false);
  const [createdLink, setCreatedLink] = useState<string | null>(null);

  const invalidateInvites = (): void => {
    void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "invitations"] });
  };

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeInvitation(id),
    onSuccess: invalidateInvites,
  });

  const resendMutation = useMutation({
    mutationFn: (id: string) => resendInvitation(id),
    onSuccess: (res) => {
      if (res.link) {
        setCreatedLink(res.link);
      }
      invalidateInvites();
    },
  });

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-fg-1">Members</h2>
          {isAdmin ? (
            <button
              type="button"
              onClick={() => {
                setCreatedLink(null);
                setInviteOpen(true);
              }}
              className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-[13px] font-medium text-accent-fg hover:opacity-90"
              data-testid="invite-button"
            >
              Invite
            </button>
          ) : null}
        </div>

        {membersQuery.isError ? (
          <p
            role="alert"
            className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
          >
            Could not load members. Try again.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-bg-elev-2 text-[11px] uppercase tracking-[0.07em] text-fg-4">
                <tr>
                  <th className="px-3 py-2 font-medium">Member</th>
                  <th className="px-3 py-2 font-medium">Email</th>
                  <th className="px-3 py-2 font-medium">Role</th>
                </tr>
              </thead>
              <tbody>
                {(membersQuery.data ?? []).map((m) => (
                  <tr key={m.user_id} className="border-t border-border" data-testid="member-row">
                    <td className="px-3 py-2 text-fg-1">{m.name}</td>
                    <td className="px-3 py-2 text-fg-3">{m.email}</td>
                    <td className="px-3 py-2 font-mono text-[12px] text-fg-1">{m.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {isAdmin ? (
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold text-fg-1">Pending invitations</h2>
          {invitesQuery.isError ? (
            <p
              role="alert"
              className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
            >
              Could not load invitations. Try again.
            </p>
          ) : (invitesQuery.data ?? []).length === 0 ? (
            <p className="text-[13px] text-fg-4">No invitations yet.</p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-left text-[13px]">
                <thead className="bg-bg-elev-2 text-[11px] uppercase tracking-[0.07em] text-fg-4">
                  <tr>
                    <th className="px-3 py-2 font-medium">Email</th>
                    <th className="px-3 py-2 font-medium">Role</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(invitesQuery.data ?? []).map((inv) => {
                    const status = invitationStatus(inv);
                    return (
                      <tr key={inv.id} className="border-t border-border" data-testid="invite-row">
                        <td className="px-3 py-2 text-fg-1">{inv.email}</td>
                        <td className="px-3 py-2 font-mono text-[12px] text-fg-1">{inv.role}</td>
                        <td className={`px-3 py-2 font-medium ${STATUS_STYLE[status]}`}>{status}</td>
                        <td className="px-3 py-2">
                          {status === "pending" ? (
                            <div className="flex items-center justify-end gap-2">
                              <button
                                type="button"
                                disabled={resendMutation.isPending}
                                onClick={() => resendMutation.mutate(inv.id)}
                                className="rounded-md px-2 py-1 text-[12px] font-medium text-fg-1 hover:bg-bg-elev-2 disabled:opacity-50"
                                data-testid={`resend-${inv.id}`}
                              >
                                Resend
                              </button>
                              <button
                                type="button"
                                disabled={revokeMutation.isPending}
                                onClick={() => revokeMutation.mutate(inv.id)}
                                className="rounded-md px-2 py-1 text-[12px] font-medium text-red hover:bg-red/10 disabled:opacity-50"
                                data-testid={`revoke-${inv.id}`}
                              >
                                Revoke
                              </button>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {createdLink ? (
            <div
              className="space-y-2 rounded-lg border border-border bg-bg-elev-1 p-4"
              data-testid="invite-link-panel"
            >
              <p className="text-[12.5px] font-medium text-fg-1">Invitation link</p>
              <p className="text-[12px] text-fg-4">
                Share this link with the invitee. It is shown once.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded-md border border-border bg-bg-base px-3 py-2 font-mono text-[12px] text-fg-1">
                  {createdLink}
                </code>
                <CopyButton value={createdLink} label="Copy link" />
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <InviteModal
        open={inviteOpen}
        workspaceId={workspaceId}
        onOpenChange={setInviteOpen}
        onCreated={(inv) => {
          if (inv.link) {
            setCreatedLink(inv.link);
          }
          invalidateInvites();
        }}
      />
    </div>
  );
}

interface InviteModalProps {
  open: boolean;
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onCreated: (inv: InvitationOut) => void;
}

function InviteModal({
  open,
  workspaceId,
  onOpenChange,
  onCreated,
}: InviteModalProps): React.ReactElement {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("QA");
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => createInvitation(workspaceId, { email, role }),
    onSuccess: (res) => {
      onCreated(res);
      setEmail("");
      setRole("QA");
      setError(null);
      onOpenChange(false);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setError("That email already belongs to a member of this workspace.");
        return;
      }
      setError("Could not create the invitation. Please try again.");
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>
            They will receive a one-time link to join this workspace.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
        >
          <div className="space-y-2">
            <label htmlFor="invite-email" className="text-[12.5px] font-medium text-fg-1">
              Email
            </label>
            <input
              id="invite-email"
              name="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="invite-role" className="text-[12.5px] font-medium text-fg-1">
              Role
            </label>
            <select
              id="invite-role"
              name="role"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            >
              {INVITE_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          {error ? (
            <p
              role="alert"
              className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
            >
              {error}
            </p>
          ) : null}

          <DialogFooter>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
              data-testid="invite-submit"
            >
              {createMutation.isPending ? "Creating…" : "Create invitation"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

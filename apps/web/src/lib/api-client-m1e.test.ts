import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/mocks/server";

import {
  ApiError,
  adminResetPassword,
  changeOwnPassword,
  createInvitation,
  type InvitationOut,
  invitationStatus,
  listInvitations,
  listMembers,
  listPasswordResetRequests,
  resendInvitation,
  revokeInvitation,
} from "./api-client";

const FUTURE = "2099-06-07T10:00:00Z";
const PAST = "2000-01-01T10:00:00Z";

function inviteRow(over: Partial<InvitationOut> = {}): InvitationOut {
  return {
    id: "inv_1",
    email: "qa@example.test",
    role: "QA",
    expires_at: FUTURE,
    accepted_at: null,
    revoked_at: null,
    link: null,
    ...over,
  };
}

describe("api-client M1e helpers", () => {
  it("invitationStatus derives lifecycle from timestamps", () => {
    expect(invitationStatus(inviteRow())).toBe("pending");
    expect(invitationStatus(inviteRow({ revoked_at: FUTURE }))).toBe("revoked");
    expect(invitationStatus(inviteRow({ accepted_at: FUTURE }))).toBe("accepted");
    expect(invitationStatus(inviteRow({ expires_at: PAST }))).toBe("expired");
  });

  it("changeOwnPassword PATCHes /users/me/password with the body", async () => {
    let seen: unknown = null;
    server.use(
      http.patch("*/api/v1/users/me/password", async ({ request }) => {
        seen = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await changeOwnPassword({ current_password: "old", new_password: "newpass12" });
    expect(seen).toEqual({ current_password: "old", new_password: "newpass12" });
  });

  it("changeOwnPassword surfaces a 400 wrong-current-password as ApiError", async () => {
    server.use(
      http.patch("*/api/v1/users/me/password", () =>
        HttpResponse.json({ code: "INVALID_PASSWORD", message: "wrong" }, { status: 400 }),
      ),
    );
    let err: unknown = null;
    try {
      await changeOwnPassword({ current_password: "bad", new_password: "newpass12" });
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
  });

  it("createInvitation posts to the workspace path and returns the link", async () => {
    let body: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/invitations", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          inviteRow({ link: "http://localhost/accept-invite?token=raw-token" }),
          { status: 201 },
        );
      }),
    );
    const res = await createInvitation("ws_1", { email: "qa@example.test", role: "QA" });
    expect(body).toEqual({ email: "qa@example.test", role: "QA" });
    expect(res.link).toContain("accept-invite?token=");
  });

  it("listInvitations unwraps the envelope items", async () => {
    server.use(
      http.get("*/api/v1/workspaces/ws_1/invitations", () =>
        HttpResponse.json({ items: [inviteRow()] }),
      ),
    );
    const items = await listInvitations("ws_1");
    expect(items).toHaveLength(1);
    expect(invitationStatus(items[0]!)).toBe("pending");
  });

  it("revokeInvitation posts to the revoke path (204)", async () => {
    let hit = false;
    server.use(
      http.post("*/api/v1/invitations/inv_1/revoke", () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await revokeInvitation("inv_1");
    expect(hit).toBe(true);
  });

  it("resendInvitation returns the rotated link", async () => {
    server.use(
      http.post("*/api/v1/invitations/inv_1/resend", () =>
        HttpResponse.json(
          inviteRow({ link: "http://localhost/accept-invite?token=rotated" }),
        ),
      ),
    );
    const res = await resendInvitation("inv_1");
    expect(res.link).toContain("token=rotated");
  });

  it("listMembers returns the roster", async () => {
    server.use(
      http.get("*/api/v1/workspaces/ws_1/members", () =>
        HttpResponse.json([
          {
            user_id: "u_1",
            email: "owner@example.test",
            name: "Owner",
            role: "OWNER",
            joined_at: "2026-05-01T00:00:00Z",
          },
        ]),
      ),
    );
    const items = await listMembers("ws_1");
    expect(items[0]?.role).toBe("OWNER");
  });

  it("adminResetPassword returns the one-time temporary password", async () => {
    server.use(
      http.post("*/api/v1/admin/users/u_2/reset-password", () =>
        HttpResponse.json({ temporaryPassword: "Tmp-9xQ2!kZ" }),
      ),
    );
    const res = await adminResetPassword("u_2");
    expect(res.temporaryPassword).toBe("Tmp-9xQ2!kZ");
  });

  it("listPasswordResetRequests returns items when encryption is configured", async () => {
    server.use(
      http.get("*/api/v1/admin/password-reset-requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "prr_1",
              email: "lost@example.test",
              expires_at: FUTURE,
              created_at: "2026-05-31T00:00:00Z",
              used_at: null,
              resetLink: "http://localhost/reset?token=abc",
            },
          ],
        }),
      ),
    );
    const res = await listPasswordResetRequests();
    expect(res.encryptionConfigured).toBe(true);
    expect(res.items).toHaveLength(1);
  });

  it("listPasswordResetRequests surfaces 503 ENCRYPTION_NOT_CONFIGURED as a flag", async () => {
    server.use(
      http.get("*/api/v1/admin/password-reset-requests", () =>
        HttpResponse.json(
          { code: "ENCRYPTION_NOT_CONFIGURED", message: "no key" },
          { status: 503 },
        ),
      ),
    );
    const res = await listPasswordResetRequests();
    expect(res.encryptionConfigured).toBe(false);
    expect(res.items).toEqual([]);
  });
});

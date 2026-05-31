import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { MembersPanel } from "@/components/settings/MembersPanel";
import { server } from "@/mocks/server";

const FUTURE = "2099-06-07T10:00:00Z";

function renderPanel(role = "ADMIN") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MembersPanel workspaceId="ws_1" currentRole={role} />
    </QueryClientProvider>,
  );
}

const member = {
  user_id: "u_1",
  email: "owner@example.test",
  name: "Owner",
  role: "OWNER",
  joined_at: "2026-05-01T00:00:00Z",
};

describe("MembersPanel", () => {
  beforeEach(() => {
    server.use(http.get("*/api/v1/workspaces/ws_1/members", () => HttpResponse.json([member])));
  });

  it("lists members", async () => {
    server.use(http.get("*/api/v1/workspaces/ws_1/invitations", () => HttpResponse.json({ items: [] })));
    renderPanel();
    expect(await screen.findByText("owner@example.test")).toBeInTheDocument();
  });

  it("hides the Invite button for non-admins", async () => {
    renderPanel("QA");
    await screen.findByText("owner@example.test");
    expect(screen.queryByTestId("invite-button")).not.toBeInTheDocument();
  });

  it("creates an invite and shows a copyable link", async () => {
    server.use(
      http.get("*/api/v1/workspaces/ws_1/invitations", () => HttpResponse.json({ items: [] })),
      http.post("*/api/v1/workspaces/ws_1/invitations", () =>
        HttpResponse.json(
          {
            id: "inv_1",
            email: "qa@example.test",
            role: "QA",
            expires_at: FUTURE,
            accepted_at: null,
            revoked_at: null,
            link: "http://localhost/accept-invite?token=new-token",
          },
          { status: 201 },
        ),
      ),
    );
    renderPanel("ADMIN");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("invite-button"));
    await user.type(await screen.findByLabelText(/email/i), "qa@example.test");
    await user.click(screen.getByTestId("invite-submit"));

    const panel = await screen.findByTestId("invite-link-panel");
    expect(within(panel).getByText(/accept-invite\?token=new-token/)).toBeInTheDocument();

    await user.click(within(panel).getByTestId("copy-button"));
    expect(await within(panel).findByText("Copied")).toBeInTheDocument();
  });

  it("revokes a pending invite and invalidates the cache", async () => {
    let listCalls = 0;
    let revoked = false;
    server.use(
      http.get("*/api/v1/workspaces/ws_1/invitations", () => {
        listCalls += 1;
        return HttpResponse.json({
          items: revoked
            ? []
            : [
                {
                  id: "inv_1",
                  email: "qa@example.test",
                  role: "QA",
                  expires_at: FUTURE,
                  accepted_at: null,
                  revoked_at: null,
                  link: null,
                },
              ],
        });
      }),
      http.post("*/api/v1/invitations/inv_1/revoke", () => {
        revoked = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPanel("ADMIN");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("revoke-inv_1"));
    await waitFor(() => {
      expect(listCalls).toBeGreaterThan(1);
    });
  });

  it("resends a pending invite and shows the rotated link", async () => {
    server.use(
      http.get("*/api/v1/workspaces/ws_1/invitations", () =>
        HttpResponse.json({
          items: [
            {
              id: "inv_1",
              email: "qa@example.test",
              role: "QA",
              expires_at: FUTURE,
              accepted_at: null,
              revoked_at: null,
              link: null,
            },
          ],
        }),
      ),
      http.post("*/api/v1/invitations/inv_1/resend", () =>
        HttpResponse.json({
          id: "inv_1",
          email: "qa@example.test",
          role: "QA",
          expires_at: FUTURE,
          accepted_at: null,
          revoked_at: null,
          link: "http://localhost/accept-invite?token=rotated",
        }),
      ),
    );
    renderPanel("ADMIN");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("resend-inv_1"));
    const panel = await screen.findByTestId("invite-link-panel");
    expect(within(panel).getByText(/token=rotated/)).toBeInTheDocument();
  });
});

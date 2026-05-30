# M1e — Local auth, invitation links, and super-admin bootstrap

## Goal

Insert a small M1e milestone between M1d and M2 so Suitest can be operated and tested without Google OAuth as the primary account path. M1e keeps the product ZERO-tier compatible: no LLM, no MCP routing changes, no agent/autonomy behavior, and no dependency on external email infrastructure.

This milestone adds:

- first-install super-admin bootstrap from environment variables,
- password login as the default web login path,
- invite-only user onboarding,
- self-service password change,
- super-admin password reset for other users,
- an interim forgot-password flow that works before SMTP exists.

M1e does not change the M1d TCM/runner/defect scope. It removes auth friction before M2, where multi-role testing becomes more important.

## Current state

The backend already uses FastAPI-Users with cookie auth, Google OAuth, and a `users` table that includes FastAPI-Users fields such as `is_superuser`, `is_verified`, and `hashed_password`. Users join workspaces through `memberships` with roles `OWNER`, `ADMIN`, `QA`, and `VIEWER`.

Current gaps:

- `/auth/register` is public because `get_register_router` is mounted.
- The login UI can rely too much on Google OAuth even though email/password auth exists.
- New users do not have an invite-only path.
- There is no first-install super-admin contract for self-host operators.
- Password reset needs email delivery, but the project has no SMTP subsystem yet.

## In scope

### Bootstrap super-admin

Add settings:

- `SUITEST_SUPERADMIN_EMAIL`
- `SUITEST_SUPERADMIN_PASSWORD`
- `SUITEST_SUPERADMIN_WORKSPACE_NAME`, default `"Default Workspace"`

During API lifespan startup, run an idempotent bootstrap service:

1. If `users` table has at least one row, skip.
2. If either super-admin email or password is missing, skip and log a warning that first-install login is not configured.
3. If both are present, create:
   - one active, verified user with `is_superuser=True`,
   - one workspace using the configured workspace name,
   - one membership for that user as `OWNER`,
   - one `WorkspaceCapability` row in ZERO / manual mode.

The password is hashed through FastAPI-Users `PasswordHelper`. The plaintext password is never logged, persisted, or returned.

### Password login first

Keep the existing FastAPI-Users cookie login endpoint:

- `POST /auth/cookie/login`

Update the frontend login route so email/password is the primary form. Google OAuth remains secondary and only appears when `SUITEST_OAUTH_GOOGLE_CLIENT_ID` and `SUITEST_OAUTH_GOOGLE_CLIENT_SECRET` are configured.

### Disable public register

Remove the FastAPI-Users register router from `apps/api/src/suitest_api/auth/router.py`.

After M1e:

- `POST /auth/register` returns 404.
- New non-bootstrap accounts are created only by accepting an invitation.
- Existing seed users remain valid for local development.

### Invitation links

Add a stateful `invitations` table. Stateless signed invite tokens are not sufficient because M1e needs revoke, resend, audit, and pending-invite listing.

Fields:

- `id` string primary key
- `workspace_id` foreign key to `workspaces.id`
- `email` lowercased string
- `role` enum limited to `ADMIN`, `QA`, `VIEWER`
- `token_hash` string containing `sha256(raw_token)`
- `expires_at` timestamp with time zone
- `accepted_at` nullable timestamp with time zone
- `revoked_at` nullable timestamp with time zone
- `created_by` nullable UUID foreign key to `users.id`
- `created_at`, `updated_at`

Add setting:

- `SUITEST_INVITE_TTL_HOURS`, default `168`

Token generation:

- Use `secrets.token_urlsafe(32)`.
- Store only the SHA-256 hash.
- Return the raw token only in create/resend responses as a copyable link:
  `{SUITEST_WEB_URL}/accept-invite?token=<raw>`

Repository:

- `InvitationRepository.create`
- `InvitationRepository.list_for_workspace`
- `InvitationRepository.get_active_by_token_hash`
- `InvitationRepository.revoke`
- `InvitationRepository.resend`
- `InvitationRepository.mark_accepted`

Service rules:

- Invite creation requires workspace `ADMIN` or `OWNER`.
- Super-admin can manage invitations across workspaces.
- A user cannot be invited if their email already belongs to a member of that workspace.
- A revoked, accepted, or expired token cannot be accepted.
- Accepting an invite creates the user if absent, then creates the membership.
- If the user already exists but is not a workspace member, accepting the invite adds the membership and updates the password only when the user has no usable password. Existing users authenticate with their current password.
- Roles in invite creation are limited to `ADMIN`, `QA`, and `VIEWER`; `OWNER` assignment stays a separate workspace-owner action.

API endpoints:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/workspaces/{workspace_id}/invitations` | `ADMIN+` | Create invite and return copyable link |
| `GET` | `/api/v1/workspaces/{workspace_id}/invitations` | `ADMIN+` | List pending, accepted, revoked, and expired invites |
| `POST` | `/api/v1/invitations/{id}/revoke` | `ADMIN+` | Revoke invite |
| `POST` | `/api/v1/invitations/{id}/resend` | `ADMIN+` | Rotate token, extend TTL, return new copyable link |
| `GET` | `/api/v1/invitations/validate?token=` | public | Return invite email, role, workspace name, and expiry |
| `POST` | `/api/v1/auth/accept-invite` | public | Accept invite, create account/membership, and set session cookie |

Audit actions:

- `invitation.created`
- `invitation.revoked`
- `invitation.resent`
- `invitation.accepted`

Audit metadata must not include raw tokens or password material.

### Change password

Add a Suitest-specific password endpoint instead of relying on generic profile update semantics:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `PATCH` | `/api/v1/users/me/password` | current active user | Change the current user's password |

Request body contains `current_password` and `new_password`. The service verifies `current_password` with FastAPI-Users `PasswordHelper`, stores only the hash of `new_password`, clears `must_change_password`, and logs `user.password_changed`.

### Super-admin password reset

Add a super-admin-only endpoint:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/admin/users/{user_id}/reset-password` | `is_superuser` | Generate a temporary password and return it once |

Behavior:

- Generate a high-entropy temporary password.
- Store only its hash.
- Return the temporary password once in the response.
- Set a `must_change_password` marker so the UI forces the user to change it after login.

If the current users table has no `must_change_password` field, M1e adds it as `BOOLEAN NOT NULL DEFAULT FALSE`.

Audit action:

- `user.password_reset_by_admin`

Audit metadata must include the target user id but never the temporary password.

### Forgot password without SMTP

Wire FastAPI-Users reset-password support, but use an interim internal delivery model until email infrastructure exists.

Endpoints:

- `POST /auth/forgot-password`
- `POST /auth/reset-password`

Override the user-manager forgot-password hook to store a reset request row for super-admin review.

Add `password_reset_requests` table:

- `id` string primary key
- `email` lowercased string
- `token_hash` string containing `sha256(reset_token)`
- `reset_link_encrypted` nullable string encrypted with `packages/core/crypto`
- `expires_at` timestamp with time zone
- `used_at` nullable timestamp with time zone
- `created_at`

Reset links are bearer access and must be encrypted at rest. If encryption is not configured, the reset-request review endpoint returns `503 ENCRYPTION_NOT_CONFIGURED` and the forgot-password hook stores only `token_hash`; production must not log reset links.

Super-admin UI exposes reset requests:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/admin/password-reset-requests` | `is_superuser` | List recent reset requests with copyable links when encryption is configured |

This is intentionally interim. SMTP delivery is out of scope for M1e.

## Out of scope

- SMTP, transactional email, email templates, or email provider configuration.
- Public self-registration.
- OAuth provider redesign beyond keeping Google as optional secondary login.
- SSO/SAML/SCIM.
- Organization-level billing or SaaS tenancy.
- LLM-dependent onboarding help.
- Changing M1d role gates for TCM, runner, defects, integrations, or audit logs.

## Frontend surfaces

### `/login`

- Email/password form is primary.
- Google button is secondary and conditionally rendered only when configured.
- Uses existing dark tokens and compact product UI style from `docs/UI_SPEC.md`.

### `/accept-invite`

- Public route.
- Reads `token` from query string.
- Calls validate endpoint to show email, workspace name, role, and expiry.
- Lets the invited user set display name and password.
- On success, session cookie is set and the app redirects to `/dashboard`.
- Expired/revoked/accepted tokens show a clear error state.

### Settings -> Account

- Current user can change password.
- Users with `must_change_password=true` are routed here after login and cannot continue until password is changed.

### Workspace Settings -> Members

- Existing members list remains.
- Add Invite button for `ADMIN+`.
- Invite modal collects email and role.
- On create/resend, show a copyable link.
- Pending invites table supports revoke and resend.

### Admin -> Users

- Visible only to `is_superuser`.
- Lists users across workspaces.
- Supports reset password and reset-request review.

## API and schema docs to update during implementation

M1e implementation must update:

- `docs/API.md` §3.1 Auth & workspace with invitation, accept-invite, admin reset, and reset-request endpoints.
- `docs/DATA_MODEL.md` with `invitations`, `password_reset_requests`, and `users.must_change_password`.
- `docs/UI_SPEC.md` with login, accept-invite, account settings, members invite, and super-admin surfaces.
- `docs/ROADMAP.md` by inserting M1e between M1d and M2.
- `packages/shared/openapi.json` after backend schema generation.

## Capability and autonomy rules

M1e is tier-agnostic and ZERO-compatible.

- No endpoint requires `require_tier(LOCAL | CLOUD)`.
- No UI feature needs `<Gated feature="ai_generation">`.
- No LLM provider or `packages/agent` code is called.
- No MCP server is invoked.
- Mutations still require audit logging.

Authorization is role-based:

- Workspace invitation management: workspace `ADMIN` or `OWNER`.
- Super-admin user reset and reset-request review: `user.is_superuser`.
- Public routes: invite validation, accept-invite, forgot-password, reset-password.

## Data integrity and security

- Invitation tokens and reset tokens are bearer secrets; store hashes, not raw token strings, except the intentionally one-time returned invite link.
- Passwords are always hashed through FastAPI-Users helpers.
- Plaintext temporary passwords are returned once and never logged.
- The first-install bootstrap password is read from env and never logged.
- Public invite validation must not leak whether an arbitrary email is registered. It only reveals data for valid, unexpired, unrevoked invite tokens.
- Revoke/resend/accept operations must be transactionally safe and audited.
- Existing users cannot be silently taken over by invite acceptance.
- Public register remains disabled.

## Testing plan

Backend pytest:

- bootstrap creates super-admin + workspace + membership when DB has zero users,
- bootstrap skips when users exist,
- bootstrap skips safely when env is incomplete,
- `/auth/register` returns 404,
- invitation create/list/revoke/resend paths with `ADMIN+` gate,
- `QA`/`VIEWER` cannot manage invitations,
- invite create rejects existing workspace member,
- accept-invite creates user and membership,
- accept-invite rejects expired/revoked/accepted tokens,
- accept-invite for existing non-member does not overwrite an existing password,
- cross-workspace invitation access returns 403 according to existing workspace membership dependency,
- self password change succeeds through `/api/v1/users/me/password` and requires current password,
- super-admin reset returns temp password once and sets `must_change_password`,
- non-super-admin reset is forbidden,
- forgot-password creates a reset request without logging token material,
- reset-password consumes token and marks request used where the hook can correlate it.

Frontend Vitest:

- login form posts email/password and handles 400/401,
- Google button hides when OAuth env/capability is unavailable,
- accept-invite validates token, renders expired/revoked states, and submits password,
- Account password-change form validates and handles server errors,
- Members invite modal creates invite and copies returned link,
- pending invites table revoke/resend actions update local query cache,
- super-admin reset flow shows one-time temp password.

E2E:

- first-install env bootstrap -> login with password -> dashboard,
- owner invites QA -> QA accepts -> QA logs in -> sees workspace,
- admin revokes invite -> revoked token cannot be accepted.

## Acceptance criteria

- [ ] **M1e-1** Super-admin bootstrap service and settings are implemented, idempotent, tested, and safe when env is incomplete.
- [ ] **M1e-2** Public register is disabled; password login is the primary web login; Google OAuth is optional secondary UI.
- [ ] **M1e-3** `invitations` schema, repository, service, endpoints, audit logging, and tests land.
- [ ] **M1e-4** `/accept-invite` frontend route creates accounts/memberships through invite-only onboarding.
- [ ] **M1e-5** Settings -> Account supports password change and enforces `must_change_password` when set.
- [ ] **M1e-6** Super-admin user reset endpoint and admin UI return one-time temporary passwords safely.
- [ ] **M1e-7** Forgot-password/reset-password routes are wired with interim super-admin reset-request review.
- [ ] **M1e-8** Docs and OpenAPI artifacts are updated: `API.md`, `DATA_MODEL.md`, `UI_SPEC.md`, `ROADMAP.md`, and generated OpenAPI.
- [ ] **M1e-9** ZERO-mode verification passes: backend pytest, frontend Vitest, and invite/login E2E.

## Suggested implementation order

1. Settings + bootstrap service + tests.
2. Disable register + login UI adjustment.
3. Invitations migration/model/repository/service.
4. Invitation endpoints + audit logging.
5. Accept-invite frontend.
6. Members invite UI.
7. Password change + `must_change_password`.
8. Super-admin reset.
9. Forgot-password interim reset-request review.
10. Docs/OpenAPI/ROADMAP updates and E2E coverage.

This order keeps the system shippable at each step and avoids mixing login changes with invitation persistence in the same PR.

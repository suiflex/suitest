# M1e Local Auth Invite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement M1e local auth, super-admin bootstrap, invite-only onboarding, password changes, admin resets, and interim reset-request review.

**Architecture:** Keep FastAPI-Users for cookie auth/password hashing and add Suitest-owned services for bootstrap, invitations, password management, and reset-request review. Store bearer tokens as SHA-256 hashes, return raw invite links only once, and keep all mutations audited through existing repository/service patterns. Frontend adds password-first login, accept-invite, members invite UI, and account/admin password surfaces without introducing any LLM or MCP dependency.

**Tech Stack:** FastAPI, FastAPI-Users, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest-asyncio, Vite React 19, TanStack Router/Query, Vitest, MSW.

---

## Files

- Create `packages/db/src/suitest_db/models/invitation.py`
- Create `packages/db/src/suitest_db/models/password_reset_request.py`
- Modify `packages/db/src/suitest_db/models/user.py`
- Modify `packages/db/src/suitest_db/models/__init__.py`
- Create `packages/db/src/suitest_db/repositories/invitations.py`
- Create `packages/db/src/suitest_db/repositories/password_reset_requests.py`
- Create `packages/db/alembic/versions/20260531_0027_m1e_auth_invites.py`
- Modify `apps/api/src/suitest_api/settings.py`
- Create `apps/api/src/suitest_api/services/bootstrap.py`
- Create `apps/api/src/suitest_api/services/invitation_service.py`
- Create `apps/api/src/suitest_api/services/password_service.py`
- Create `apps/api/src/suitest_api/routers/invitations.py`
- Create `apps/api/src/suitest_api/routers/admin_users.py`
- Modify `apps/api/src/suitest_api/auth/router.py`
- Modify `apps/api/src/suitest_api/auth/manager.py`
- Modify `apps/api/src/suitest_api/main.py`
- Create `apps/api/tests/test_m1e_bootstrap.py`
- Create `apps/api/tests/test_m1e_invitations.py`
- Create `apps/api/tests/test_m1e_passwords.py`
- Modify `apps/api/tests/test_auth.py`
- Modify `apps/web/src/routes/login.tsx`
- Modify `apps/web/src/routes/login.test.tsx`
- Create `apps/web/src/routes/accept-invite.tsx`
- Create `apps/web/src/routes/accept-invite.test.tsx`
- Modify `apps/web/src/lib/api-client.ts`
- Update `docs/API.md`, `docs/DATA_MODEL.md`, `docs/UI_SPEC.md`, `docs/ROADMAP.md`

## Task 1: Backend schema and bootstrap

**Files:**
- Test: `apps/api/tests/test_m1e_bootstrap.py`
- Create: `packages/db/src/suitest_db/models/invitation.py`
- Create: `packages/db/src/suitest_db/models/password_reset_request.py`
- Modify: `packages/db/src/suitest_db/models/user.py`
- Modify: `packages/db/src/suitest_db/models/__init__.py`
- Create: `packages/db/alembic/versions/20260531_0027_m1e_auth_invites.py`
- Modify: `apps/api/src/suitest_api/settings.py`
- Create: `apps/api/src/suitest_api/services/bootstrap.py`
- Modify: `apps/api/src/suitest_api/main.py`

- [ ] Write failing tests for bootstrap create/skip/incomplete-env behavior.
- [ ] Run `uv run pytest apps/api/tests/test_m1e_bootstrap.py -q` and confirm failures are for missing bootstrap code.
- [ ] Add `must_change_password` to `User`, new invitation/reset models, registry import, and Alembic migration.
- [ ] Add `superadmin_email`, `superadmin_password`, `superadmin_workspace_name`, and `invite_ttl_hours` settings.
- [ ] Implement `bootstrap_first_install_superadmin(session, settings)` and call it from API lifespan using the app session dependency.
- [ ] Run `uv run pytest apps/api/tests/test_m1e_bootstrap.py -q`.

## Task 2: Register disable and password-first auth API

**Files:**
- Test: `apps/api/tests/test_auth.py`
- Test: `apps/api/tests/test_m1e_passwords.py`
- Modify: `apps/api/src/suitest_api/auth/router.py`
- Modify: `apps/api/src/suitest_api/auth/manager.py`
- Create: `apps/api/src/suitest_api/services/password_service.py`
- Create: `apps/api/src/suitest_api/routers/admin_users.py`
- Modify: `apps/api/src/suitest_api/main.py`

- [ ] Add tests that `/auth/register` returns 404 and `/users/me` remains protected.
- [ ] Add password-change tests for success, wrong current password, and `must_change_password` clearing.
- [ ] Add super-admin reset tests for superuser-only access, temporary password return once, and `must_change_password=True`.
- [ ] Run targeted tests and confirm they fail for missing behavior.
- [ ] Remove `get_register_router` from auth router.
- [ ] Wire FastAPI-Users forgot/reset-password routers in auth router.
- [ ] Implement `PasswordService.change_own_password` and `PasswordService.reset_user_password_as_superadmin`.
- [ ] Add `/api/v1/users/me/password`, `/api/v1/admin/users/{user_id}/reset-password`, and `/api/v1/admin/password-reset-requests` routes.
- [ ] Run `uv run pytest apps/api/tests/test_auth.py apps/api/tests/test_m1e_passwords.py -q`.

## Task 3: Invitation backend

**Files:**
- Test: `apps/api/tests/test_m1e_invitations.py`
- Create: `packages/db/src/suitest_db/repositories/invitations.py`
- Create: `packages/db/src/suitest_db/repositories/password_reset_requests.py`
- Create: `apps/api/src/suitest_api/services/invitation_service.py`
- Create: `apps/api/src/suitest_api/routers/invitations.py`
- Modify: `apps/api/src/suitest_api/main.py`

- [ ] Add tests for create/list/revoke/resend, ADMIN+ gate, existing-member rejection, validate token, accept invite creates user+membership, expired/revoked/accepted token rejection, and existing-user non-member acceptance without password overwrite.
- [ ] Run `uv run pytest apps/api/tests/test_m1e_invitations.py -q` and confirm missing-route/service failures.
- [ ] Implement token hashing helpers and invitation repository methods.
- [ ] Implement `InvitationService` with role checks, token rotation, accept transaction, and audit-action names.
- [ ] Add public and authenticated invitation routes.
- [ ] Run `uv run pytest apps/api/tests/test_m1e_invitations.py -q`.

## Task 4: Frontend password login and accept invite

**Files:**
- Modify: `apps/web/src/routes/login.tsx`
- Modify: `apps/web/src/routes/login.test.tsx`
- Create: `apps/web/src/routes/accept-invite.tsx`
- Create: `apps/web/src/routes/accept-invite.test.tsx`
- Modify: `apps/web/src/lib/api-client.ts`

- [ ] Add failing Vitest coverage for email/password login posting form-encoded data to `/auth/cookie/login`.
- [ ] Add failing Vitest coverage for Google button as secondary and error rendering.
- [ ] Add failing Vitest coverage for accept-invite validate, expired state, and submit.
- [ ] Run `pnpm --dir apps/web vitest run src/routes/login.test.tsx src/routes/accept-invite.test.tsx`.
- [ ] Implement password-first login UI.
- [ ] Implement accept-invite route with validate and submit calls.
- [ ] Add typed helper functions for invitation/auth endpoints only where route components need them.
- [ ] Run targeted Vitest command again.

## Task 5: Docs, generated artifacts, and verification

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/DATA_MODEL.md`
- Modify: `docs/UI_SPEC.md`
- Modify: `docs/ROADMAP.md`
- Generated if project command is available: `packages/shared/openapi.json`

- [ ] Update API, data model, UI spec, and roadmap to include M1e.
- [ ] Run backend targeted tests: `uv run pytest apps/api/tests/test_auth.py apps/api/tests/test_m1e_bootstrap.py apps/api/tests/test_m1e_invitations.py apps/api/tests/test_m1e_passwords.py -q`.
- [ ] Run frontend targeted tests: `pnpm --dir apps/web vitest run src/routes/login.test.tsx src/routes/accept-invite.test.tsx`.
- [ ] Run type/lint checks that fit the touched surface: `uv run mypy apps/api/src packages/db/src` and `pnpm --dir apps/web tsc --noEmit`.
- [ ] Run `rtk git status --short` and review the final diff for secrets, raw tokens, and unrelated churn.

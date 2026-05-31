import { useSuspenseQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

export interface CurrentUserMembership {
  workspace_id: string;
  role: string;
  workspace: {
    id: string;
    slug: string;
    name: string;
  };
}

export interface CurrentUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  /**
   * True when an admin reset forced a temporary password (M1e). Optional in the
   * type because the committed `MeResponse` OpenAPI schema does not yet expose
   * it; the backend sets it after `POST /admin/users/:id/reset-password`. We
   * treat a missing value as `false`.
   */
  must_change_password?: boolean;
  /** Cross-workspace super-admin flag — gates the Admin nav + routes (M1e). */
  is_superuser?: boolean;
  memberships: CurrentUserMembership[];
}

/**
 * Suspense-backed reader for `GET /auth/me`. Routes that need the current
 * user can call this directly; the `_app` route guard already ensures the
 * query is in cache (via `ensureQueryData`) before any descendant renders.
 */
export function useCurrentUser(): { data: CurrentUser } {
  return useSuspenseQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => (await api.get<CurrentUser>("/auth/me")).data,
  });
}

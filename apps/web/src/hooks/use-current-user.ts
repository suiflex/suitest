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

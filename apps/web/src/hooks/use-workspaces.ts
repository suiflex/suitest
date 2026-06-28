import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

type WorkspacePublic = components["schemas"]["WorkspacePublic"];

export interface CreateWorkspaceInput {
  name: string;
  slug?: string;
}

/**
 * Create a workspace via ``POST /workspaces`` (bootstrap blocker #1). The caller
 * becomes the OWNER, so a brand-new or invited user with no workspace can make
 * their first one entirely from the UI.
 *
 * On success we switch to the new workspace and clear the active project (the
 * new workspace has no projects yet), then invalidate `/auth/me` + `/projects`
 * so the shell + Cases screen reconcile against the new tenant.
 */
export function useCreateWorkspace(): UseMutationResult<
  WorkspacePublic,
  Error,
  CreateWorkspaceInput
> {
  const queryClient = useQueryClient();
  const setWorkspaceId = useActiveWorkspace((s) => s.setWorkspaceId);
  const setProjectId = useActiveProject((s) => s.setProjectId);
  return useMutation({
    mutationFn: async (input: CreateWorkspaceInput) => {
      const res = await api.post<WorkspacePublic>("/workspaces", input);
      return res.data;
    },
    onSuccess: (workspace) => {
      setWorkspaceId(workspace.id);
      setProjectId(null);
      void queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

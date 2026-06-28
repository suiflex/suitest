import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

type ProjectPublic = components["schemas"]["ProjectPublic"];

export interface CreateProjectInput {
  name: string;
  slug?: string;
  description?: string;
}

/**
 * Create a project via ``POST /projects`` (bootstrap blocker #1).
 *
 * On success the new project becomes the active project so the Cases screen —
 * which 422s without a `projectId` — immediately resolves, and the `["projects"]`
 * list (seeded in `routes/_app.tsx#beforeLoad`) is invalidated.
 */
export function useCreateProject(): UseMutationResult<ProjectPublic, Error, CreateProjectInput> {
  const queryClient = useQueryClient();
  const setProjectId = useActiveProject((s) => s.setProjectId);
  return useMutation({
    mutationFn: async (input: CreateProjectInput) => {
      const res = await api.post<ProjectPublic>("/projects", input);
      return res.data;
    },
    onSuccess: (project) => {
      setProjectId(project.id);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

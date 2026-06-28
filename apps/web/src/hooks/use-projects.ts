import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

type ProjectPublic = components["schemas"]["ProjectPublic"];

export interface CreateProjectInput {
  name: string;
  slug?: string;
  description?: string;
}

/** ``GET /projects/:id`` — carries ``gating_suite_id`` (which suite gates deploys). */
export function useProject(projectId: string | null): UseQueryResult<ProjectPublic> {
  return useQuery({
    queryKey: ["project", projectId] as const,
    enabled: projectId !== null,
    queryFn: async () => {
      const res = await api.get<ProjectPublic>(`/projects/${projectId ?? ""}`);
      return res.data;
    },
  });
}

export interface SetGatingSuiteInput {
  projectId: string;
  suiteId: string | null;
}

/**
 * Mark (or clear) the project's gating suite via ``PATCH /projects/:id`` —
 * journey step 9. ZERO-friendly: deterministic gate, no LLM.
 */
export function useSetGatingSuite(): UseMutationResult<ProjectPublic, Error, SetGatingSuiteInput> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, suiteId }: SetGatingSuiteInput) => {
      const res = await api.patch<ProjectPublic>(`/projects/${projectId}`, {
        gatingSuiteId: suiteId,
      });
      return res.data;
    },
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ["project", project.id] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
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

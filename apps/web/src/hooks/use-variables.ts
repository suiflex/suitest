import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

export interface VariablePublic {
  id: string;
  workspaceId?: string | null;
  suiteId?: string | null;
  key: string;
  value?: string | null;
  description?: string | null;
  isSecret: boolean;
  hasValue: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface VariableCreateInput {
  key: string;
  value?: string | undefined;
  description?: string | undefined;
  isSecret?: boolean | undefined;
}

export interface VariableUpdateInput {
  key?: string | undefined;
  value?: string | undefined;
  description?: string | undefined;
  isSecret?: boolean | undefined;
}

export interface ResolvedVariableItem {
  key: string;
  value?: string | null;
  isSecret: boolean;
  sourceScope: "workspace" | "suite" | "dataset" | "env";
  description?: string | null;
}

/**
 * Fetch workspace-level variables.
 */
export function useWorkspaceVariables(
  workspaceIdOverride?: string | null
): UseQueryResult<VariablePublic[]> {
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const wsId = workspaceIdOverride ?? activeWorkspaceId;

  return useQuery({
    queryKey: ["variables", "workspace", wsId],
    queryFn: async () => {
      if (!wsId) return [];
      const res = await api.get<VariablePublic[]>(`/workspaces/${wsId}/variables`);
      return res.data;
    },
    enabled: Boolean(wsId),
  });
}

/**
 * Create a workspace variable.
 */
export function useCreateWorkspaceVariable(
  workspaceIdOverride?: string | null
): UseMutationResult<VariablePublic, Error, VariableCreateInput> {
  const queryClient = useQueryClient();
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const wsId = workspaceIdOverride ?? activeWorkspaceId;

  return useMutation({
    mutationFn: async (input: VariableCreateInput) => {
      if (!wsId) throw new Error("Workspace ID is required");
      const res = await api.post<VariablePublic>(`/workspaces/${wsId}/variables`, input);
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "workspace", wsId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Update a workspace variable.
 */
export function useUpdateWorkspaceVariable(
  workspaceIdOverride?: string | null
): UseMutationResult<
  VariablePublic,
  Error,
  { variableId: string; input: VariableUpdateInput }
> {
  const queryClient = useQueryClient();
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const wsId = workspaceIdOverride ?? activeWorkspaceId;

  return useMutation({
    mutationFn: async ({ variableId, input }) => {
      if (!wsId) throw new Error("Workspace ID is required");
      const res = await api.patch<VariablePublic>(
        `/workspaces/${wsId}/variables/${variableId}`,
        input
      );
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "workspace", wsId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Delete a workspace variable.
 */
export function useDeleteWorkspaceVariable(
  workspaceIdOverride?: string | null
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const wsId = workspaceIdOverride ?? activeWorkspaceId;

  return useMutation({
    mutationFn: async (variableId: string) => {
      if (!wsId) throw new Error("Workspace ID is required");
      await api.delete(`/workspaces/${wsId}/variables/${variableId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "workspace", wsId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Fetch suite-level variables.
 */
export function useSuiteVariables(
  suiteId?: string | null
): UseQueryResult<VariablePublic[]> {
  return useQuery({
    queryKey: ["variables", "suite", suiteId],
    queryFn: async () => {
      if (!suiteId) return [];
      const res = await api.get<VariablePublic[]>(`/suites/${suiteId}/variables`);
      return res.data;
    },
    enabled: Boolean(suiteId),
  });
}

/**
 * Create a suite variable.
 */
export function useCreateSuiteVariable(
  suiteId?: string | null
): UseMutationResult<VariablePublic, Error, VariableCreateInput> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: VariableCreateInput) => {
      if (!suiteId) throw new Error("Suite ID is required");
      const res = await api.post<VariablePublic>(`/suites/${suiteId}/variables`, input);
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "suite", suiteId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Update a suite variable.
 */
export function useUpdateSuiteVariable(
  suiteId?: string | null
): UseMutationResult<
  VariablePublic,
  Error,
  { variableId: string; input: VariableUpdateInput }
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ variableId, input }) => {
      if (!suiteId) throw new Error("Suite ID is required");
      const res = await api.patch<VariablePublic>(
        `/suites/${suiteId}/variables/${variableId}`,
        input
      );
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "suite", suiteId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Delete a suite variable.
 */
export function useDeleteSuiteVariable(
  suiteId?: string | null
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (variableId: string) => {
      if (!suiteId) throw new Error("Suite ID is required");
      await api.delete(`/suites/${suiteId}/variables/${variableId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["variables", "suite", suiteId] });
      void queryClient.invalidateQueries({ queryKey: ["variables", "resolved"] });
    },
  });
}

/**
 * Fetch resolved hierarchy variables for a workspace (and optionally suite).
 */
export function useResolvedVariables(
  suiteId?: string | null,
  workspaceIdOverride?: string | null
): UseQueryResult<ResolvedVariableItem[]> {
  const activeWorkspaceId = useActiveWorkspace((s) => s.workspaceId);
  const wsId = workspaceIdOverride ?? activeWorkspaceId;

  return useQuery({
    queryKey: ["variables", "resolved", wsId, suiteId],
    queryFn: async () => {
      if (!wsId) return [];
      const url = `/workspaces/${wsId}/variables/resolved${
        suiteId ? `?suite_id=${encodeURIComponent(suiteId)}` : ""
      }`;
      const res = await api.get<ResolvedVariableItem[]>(url);
      return res.data;
    },
    enabled: Boolean(wsId),
  });
}

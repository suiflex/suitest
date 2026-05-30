import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
  type UseMutationResult,
  type UseQueryResult,
  type UseSuspenseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type CasesPage = components["schemas"]["Page_TestCaseListItem_"];
type CaseDetail = components["schemas"]["TestCaseDetail"];
type SuitesPage = { items: components["schemas"]["SuitePublic"][] };
type TargetKind = components["schemas"]["TargetKind"];

export function useSuites(): UseSuspenseQueryResult<SuitesPage> {
  return useSuspenseQuery({
    queryKey: ["suites"] as const,
    queryFn: async () => {
      const res = await api.get<SuitesPage>("/suites");
      return res.data;
    },
  });
}

export function useTestCases(suiteId?: string): UseSuspenseQueryResult<CasesPage> {
  return useSuspenseQuery({
    queryKey: ["test-cases", { suiteId }] as const,
    queryFn: async () => {
      const res = await api.get<CasesPage>("/test-cases", {
        params: suiteId ? { suiteId } : undefined,
      });
      return res.data;
    },
  });
}

export function useTestCase(caseId: string | undefined): UseQueryResult<CaseDetail> {
  return useQuery({
    queryKey: ["test-cases", caseId] as const,
    enabled: Boolean(caseId),
    queryFn: async () => {
      const res = await api.get<CaseDetail>(`/test-cases/${caseId ?? ""}`);
      return res.data;
    },
  });
}

// ---------------------------------------------------------------------------
// Write mutations — M1-12 step editor
// ---------------------------------------------------------------------------

interface StepAppendPayload {
  action: string;
  expected: string;
  code: string | null;
  mcpProvider: string;
  targetKind: TargetKind;
}

interface StepReplacePayload {
  steps: Array<{
    action: string;
    expected: string;
    code: string | null;
    mcpProvider: string;
    targetKind: TargetKind;
    order: number;
  }>;
}

/**
 * Append a single step to a test case via ``POST /test-cases/:id/steps``.
 * Automatically invalidates the case query on success.
 */
export function useAddStep(caseId: string): UseMutationResult<CaseDetail, Error, StepAppendPayload> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: StepAppendPayload) => {
      const res = await api.post<CaseDetail>(`/test-cases/${caseId}/steps`, payload);
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
    },
  });
}

/**
 * Bulk-replace all steps via ``PATCH /test-cases/:id/steps``.
 * Automatically invalidates the case query on success.
 */
export function useReplaceSteps(caseId: string): UseMutationResult<CaseDetail, Error, StepReplacePayload> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: StepReplacePayload) => {
      const res = await api.patch<CaseDetail>(`/test-cases/${caseId}/steps`, payload);
      return res.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Soft-delete + restore — M1d-23 undo affordance
// ---------------------------------------------------------------------------

/**
 * Soft-delete a test case via ``DELETE /test-cases/:id``. Returns 204; the
 * record is hidden from list queries until ``POST /test-cases/:id/restore``.
 */
export function useDeleteTestCase(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (caseId: string) => {
      await api.delete(`/test-cases/${caseId}`);
    },
    onSuccess: (_data, caseId) => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
    },
  });
}

/**
 * Restore a soft-deleted test case via ``POST /test-cases/:id/restore``.
 * Idempotent per docs/API.md §3.3 — re-POST after restore returns 204.
 */
export function useRestoreTestCase(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (caseId: string) => {
      await api.post(`/test-cases/${caseId}/restore`);
    },
    onSuccess: (_data, caseId) => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
    },
  });
}

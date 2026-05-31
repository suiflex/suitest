import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
  type UseMutationResult,
  type UseQueryResult,
  type UseSuspenseQueryResult,
} from "@tanstack/react-query";

import { bulkUpdate, reorderSteps } from "@/lib/api-client";
import type { BulkUpdateRequest, BulkUpdateResponse } from "@/lib/api-client";
import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

type CasesPage = components["schemas"]["Page_TestCaseListItem_"];
type CaseDetail = components["schemas"]["TestCaseDetail"];
type SuitesPage = { items: components["schemas"]["SuitePublic"][] };
type TargetKind = components["schemas"]["TargetKind"];

export function useSuites(): UseSuspenseQueryResult<SuitesPage> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["suites", projectId] as const,
    // Backend returns a bare `SuitePublic[]`; wrap as `{ items }` so consumers
    // (which read `suites.items`) get an iterable instead of `undefined`.
    queryFn: async () => {
      const res = await api.get<components["schemas"]["SuitePublic"][]>("/suites", {
        params: { projectId },
      });
      return { items: res.data };
    },
  });
}

export function useTestCases(suiteId?: string): UseSuspenseQueryResult<CasesPage> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["test-cases", { suiteId, projectId }] as const,
    queryFn: async () => {
      // The backend requires exactly one of suiteId / projectId. When the
      // caller scopes to a suite, send that; otherwise list every case in the
      // active project (the Cases tree groups them under their suites).
      const params = suiteId ? { suiteId } : { projectId };
      const res = await api.get<CasesPage>("/test-cases", { params });
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
export function useAddStep(
  caseId: string,
): UseMutationResult<CaseDetail, Error, StepAppendPayload> {
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
export function useReplaceSteps(
  caseId: string,
): UseMutationResult<CaseDetail, Error, StepReplacePayload> {
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

// ---------------------------------------------------------------------------
// Step reorder — M1-14
// ---------------------------------------------------------------------------

/**
 * Reorder steps via ``PATCH /test-cases/:id/steps/reorder``.
 * Automatically invalidates the case query on success.
 */
export function useReorderSteps(caseId: string): UseMutationResult<CaseDetail, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (stepIdsInOrder: string[]) => reorderSteps(caseId, stepIdsInOrder),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases", caseId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Bulk operations — M1-15b
// ---------------------------------------------------------------------------

/**
 * Bulk-update test cases via ``POST /test-cases/bulk-update``.
 * Automatically invalidates the full test-cases query on success.
 */
export function useBulkUpdate(): UseMutationResult<BulkUpdateResponse, Error, BulkUpdateRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BulkUpdateRequest) => bulkUpdate(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["test-cases"] });
    },
  });
}

import {
  useQuery,
  useSuspenseQuery,
  type UseQueryResult,
  type UseSuspenseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type CasesPage = components["schemas"]["Page_TestCaseListItem_"];
type CaseDetail = components["schemas"]["TestCaseDetail"];
type SuitesPage = { items: components["schemas"]["SuitePublic"][] };

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

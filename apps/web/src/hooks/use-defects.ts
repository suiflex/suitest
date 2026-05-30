import {
  useMutation,
  useSuspenseQuery,
  type UseMutationResult,
  type UseSuspenseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type DefectsPage = components["schemas"]["Page_DefectListItem_"];
type DefectDetail = components["schemas"]["DefectDetail"];

interface Filter {
  status?: string;
}

export function useDefects(filter: Filter = {}): UseSuspenseQueryResult<DefectsPage> {
  return useSuspenseQuery({
    queryKey: ["defects", filter] as const,
    queryFn: async () => {
      const res = await api.get<DefectsPage>("/defects", { params: filter });
      return res.data;
    },
  });
}

/**
 * Fetch DefectDetail on demand (e.g. user clicks "Open run" on a defect
 * card). Resolves with the detail or throws an ApiError. Used by M1d-32
 * to traverse defect -> run_public_id -> run detail.
 */
export function useFetchDefectDetail(): UseMutationResult<DefectDetail, Error, string> {
  return useMutation({
    mutationFn: async (publicId: string) => {
      const res = await api.get<DefectDetail>(`/defects/${publicId}`);
      return res.data;
    },
  });
}

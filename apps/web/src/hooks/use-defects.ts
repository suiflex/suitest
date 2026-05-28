import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type DefectsPage = components["schemas"]["Page_DefectListItem_"];

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

import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type Matrix = components["schemas"]["TraceabilityMatrix"];

export function useTraceabilityMatrix(): UseSuspenseQueryResult<Matrix> {
  return useSuspenseQuery({
    queryKey: ["traceability", "matrix"] as const,
    queryFn: async () => (await api.get<Matrix>("/traceability/matrix")).data,
  });
}

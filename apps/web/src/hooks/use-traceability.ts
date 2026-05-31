import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

type Matrix = components["schemas"]["TraceabilityMatrix"];

export function useTraceabilityMatrix(): UseSuspenseQueryResult<Matrix> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["traceability", "matrix", projectId] as const,
    queryFn: async () =>
      (await api.get<Matrix>("/traceability/matrix", { params: { projectId } })).data,
  });
}

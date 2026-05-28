import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type Page = components["schemas"]["Page_DocumentListItem_"];

export function useDocuments(): UseSuspenseQueryResult<Page> {
  return useSuspenseQuery({
    queryKey: ["documents"] as const,
    queryFn: async () => (await api.get<Page>("/documents")).data,
  });
}

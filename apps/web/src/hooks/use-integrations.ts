import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type IntegrationsPage = {
  items: components["schemas"]["IntegrationListItem"][];
};

export interface McpProvider {
  id: string;
  name: string;
  kind: string;
  transport: "stdio" | "SSE" | "WS";
  bundled: boolean;
  health: "healthy" | "degraded" | "down" | "unchecked";
  last_checked_at: string | null;
}
export interface McpProvidersPage {
  items: McpProvider[];
}

export function useIntegrations(): UseSuspenseQueryResult<IntegrationsPage> {
  return useSuspenseQuery({
    queryKey: ["integrations"] as const,
    // Backend returns a bare `IntegrationListItem[]`; wrap as `{ items }` so
    // consumers (which read `integrations.items`) don't crash on `undefined`.
    queryFn: async () => {
      const res = await api.get<
        components["schemas"]["IntegrationListItem"][] | { items: components["schemas"]["IntegrationListItem"][] }
      >("/integrations");
      return { items: Array.isArray(res.data) ? res.data : res.data.items };
    },
  });
}

export function useMcpProviders(): UseSuspenseQueryResult<McpProvidersPage> {
  return useSuspenseQuery({
    queryKey: ["mcp", "providers"] as const,
    queryFn: async () => (await api.get<McpProvidersPage>("/mcp/providers")).data,
  });
}

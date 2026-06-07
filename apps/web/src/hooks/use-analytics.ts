import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

type Coverage = components["schemas"]["CoverageOut"];
type Readiness = components["schemas"]["ReadinessOut"];
type PassRate = components["schemas"]["PassRateSeriesOut"];
type Flaky = { items: components["schemas"]["FlakyCaseOut"][] };
type Heatmap = { cells: components["schemas"]["HeatmapCell"][] };

export function useAnalyticsReadiness(): UseSuspenseQueryResult<Readiness> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["analytics", "readiness", projectId] as const,
    queryFn: async () =>
      (await api.get<Readiness>("/analytics/readiness", { params: { projectId } })).data,
  });
}

export function useAnalyticsCoverage(): UseSuspenseQueryResult<Coverage> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["analytics", "coverage", projectId] as const,
    queryFn: async () =>
      (await api.get<Coverage>("/analytics/coverage", { params: { projectId } })).data,
  });
}

export function useAnalyticsPassRate(period = "14d"): UseSuspenseQueryResult<PassRate> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["analytics", "pass-rate", projectId, period] as const,
    queryFn: async () =>
      (await api.get<PassRate>("/analytics/pass-rate", { params: { projectId, period } })).data,
  });
}

export function useAnalyticsFlaky(limit = 5): UseSuspenseQueryResult<Flaky> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["analytics", "flaky", projectId, limit] as const,
    // Backend returns a bare `FlakyCaseOut[]`; wrap it so consumers can read
    // `.items` (and stay stable if the endpoint later paginates).
    queryFn: async () => {
      const res = await api.get<
        components["schemas"]["FlakyCaseOut"][] | { items: components["schemas"]["FlakyCaseOut"][] }
      >("/analytics/flaky", { params: { projectId, limit } });
      return { items: Array.isArray(res.data) ? res.data : res.data.items };
    },
  });
}

export function useAnalyticsHeatmap(days = 14): UseSuspenseQueryResult<Heatmap> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: ["analytics", "heatmap", projectId, days] as const,
    // Backend returns a bare `HeatmapCell[]`; wrap it as `{ cells }` for the
    // `<Heatmap cells={...} />` consumer.
    queryFn: async () => {
      const res = await api.get<
        components["schemas"]["HeatmapCell"][] | { cells: components["schemas"]["HeatmapCell"][] }
      >("/analytics/heatmap", { params: { projectId, days } });
      return { cells: Array.isArray(res.data) ? res.data : res.data.cells };
    },
  });
}

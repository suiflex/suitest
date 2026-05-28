import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type Coverage = components["schemas"]["CoverageOut"];
type Readiness = components["schemas"]["ReadinessOut"];
type PassRate = components["schemas"]["PassRateSeriesOut"];
type Flaky = { items: components["schemas"]["FlakyCaseOut"][] };
type Heatmap = { cells: components["schemas"]["HeatmapCell"][] };

export function useAnalyticsReadiness(): UseSuspenseQueryResult<Readiness> {
  return useSuspenseQuery({
    queryKey: ["analytics", "readiness"] as const,
    queryFn: async () => (await api.get<Readiness>("/analytics/readiness")).data,
  });
}

export function useAnalyticsCoverage(): UseSuspenseQueryResult<Coverage> {
  return useSuspenseQuery({
    queryKey: ["analytics", "coverage"] as const,
    queryFn: async () => (await api.get<Coverage>("/analytics/coverage")).data,
  });
}

export function useAnalyticsPassRate(period = "14d"): UseSuspenseQueryResult<PassRate> {
  return useSuspenseQuery({
    queryKey: ["analytics", "pass-rate", period] as const,
    queryFn: async () =>
      (await api.get<PassRate>("/analytics/pass-rate", { params: { period } })).data,
  });
}

export function useAnalyticsFlaky(limit = 5): UseSuspenseQueryResult<Flaky> {
  return useSuspenseQuery({
    queryKey: ["analytics", "flaky", limit] as const,
    queryFn: async () =>
      (await api.get<Flaky>("/analytics/flaky", { params: { limit } })).data,
  });
}

export function useAnalyticsHeatmap(days = 14): UseSuspenseQueryResult<Heatmap> {
  return useSuspenseQuery({
    queryKey: ["analytics", "heatmap", days] as const,
    queryFn: async () =>
      (await api.get<Heatmap>("/analytics/heatmap", { params: { days } })).data,
  });
}

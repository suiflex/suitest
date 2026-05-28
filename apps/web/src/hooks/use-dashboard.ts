import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type Kpis = components["schemas"]["KpisOut"];
type PassRateSeries = components["schemas"]["PassRateSeriesOut"];
type Coverage = components["schemas"]["CoverageOut"];
type Readiness = components["schemas"]["ReadinessOut"];
type RunsPage = components["schemas"]["Page_RunListItem_"];

/**
 * `/audit-logs?action=agent.*` is not part of the M1a backend yet. We model
 * the response shape locally so the Dashboard can wire the query today and
 * stay compatible when the endpoint lands.
 */
export interface AgentActivityEntry {
  id: string;
  action: string;
  actor: string;
  message: string;
  at: string;
}
export interface AgentActivityPage {
  items: AgentActivityEntry[];
}

const DASHBOARD_KEYS = {
  kpis: (period: string) => ["analytics", "kpis", period] as const,
  passRate: (period: string) => ["analytics", "pass-rate", period] as const,
  coverage: () => ["analytics", "coverage"] as const,
  readiness: () => ["analytics", "readiness"] as const,
  recentRuns: (limit: number) => ["runs", { limit }] as const,
  agentActivity: (limit: number) => ["audit-logs", "agent", limit] as const,
};

export function useDashboardKpis(period: string): UseSuspenseQueryResult<Kpis> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.kpis(period),
    queryFn: async () => {
      const res = await api.get<Kpis>("/analytics/kpis", { params: { period } });
      return res.data;
    },
  });
}

export function useDashboardPassRate(period: string): UseSuspenseQueryResult<PassRateSeries> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.passRate(period),
    queryFn: async () => {
      const res = await api.get<PassRateSeries>("/analytics/pass-rate", { params: { period } });
      return res.data;
    },
  });
}

export function useDashboardCoverage(): UseSuspenseQueryResult<Coverage> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.coverage(),
    queryFn: async () => {
      const res = await api.get<Coverage>("/analytics/coverage");
      return res.data;
    },
  });
}

export function useDashboardReadiness(): UseSuspenseQueryResult<Readiness> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.readiness(),
    queryFn: async () => {
      const res = await api.get<Readiness>("/analytics/readiness");
      return res.data;
    },
  });
}

export function useRecentRuns(limit: number): UseSuspenseQueryResult<RunsPage> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.recentRuns(limit),
    queryFn: async () => {
      const res = await api.get<RunsPage>("/runs", { params: { limit } });
      return res.data;
    },
  });
}

export function useAgentActivity(limit: number): UseSuspenseQueryResult<AgentActivityPage> {
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.agentActivity(limit),
    queryFn: async () => {
      // Stubbed in M1b — the backend endpoint ships later. Returning empty is
      // fine because the screen renders an EmptyState whenever items.length is
      // 0 (which is always the case in ZERO).
      const res = await api.get<AgentActivityPage>("/audit-logs", {
        params: { action: "agent.*", limit },
      });
      return res.data;
    },
  });
}

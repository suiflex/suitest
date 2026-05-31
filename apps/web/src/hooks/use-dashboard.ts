import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveProject } from "@/stores/use-active-project";

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
  kpis: (projectId: string | null, period: string) =>
    ["analytics", "kpis", projectId, period] as const,
  passRate: (projectId: string | null, period: string) =>
    ["analytics", "pass-rate", projectId, period] as const,
  coverage: (projectId: string | null) => ["analytics", "coverage", projectId] as const,
  readiness: (projectId: string | null) => ["analytics", "readiness", projectId] as const,
  recentRuns: (projectId: string | null, limit: number) => ["runs", { projectId, limit }] as const,
  agentActivity: (limit: number) => ["audit-logs", "agent", limit] as const,
};

export function useDashboardKpis(period: string): UseSuspenseQueryResult<Kpis> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.kpis(projectId, period),
    queryFn: async () => {
      const res = await api.get<Kpis>("/analytics/kpis", { params: { projectId, period } });
      return res.data;
    },
  });
}

export function useDashboardPassRate(period: string): UseSuspenseQueryResult<PassRateSeries> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.passRate(projectId, period),
    queryFn: async () => {
      const res = await api.get<PassRateSeries>("/analytics/pass-rate", {
        params: { projectId, period },
      });
      return res.data;
    },
  });
}

export function useDashboardCoverage(): UseSuspenseQueryResult<Coverage> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.coverage(projectId),
    queryFn: async () => {
      const res = await api.get<Coverage>("/analytics/coverage", { params: { projectId } });
      return res.data;
    },
  });
}

export function useDashboardReadiness(): UseSuspenseQueryResult<Readiness> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.readiness(projectId),
    queryFn: async () => {
      const res = await api.get<Readiness>("/analytics/readiness", { params: { projectId } });
      return res.data;
    },
  });
}

export function useRecentRuns(limit: number): UseSuspenseQueryResult<RunsPage> {
  const projectId = useActiveProject((s) => s.projectId);
  return useSuspenseQuery({
    queryKey: DASHBOARD_KEYS.recentRuns(projectId, limit),
    queryFn: async () => {
      const res = await api.get<RunsPage>("/runs", { params: { projectId, limit } });
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

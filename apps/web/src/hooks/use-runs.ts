import {
  useQuery,
  useSuspenseQuery,
  type UseQueryResult,
  type UseSuspenseQueryResult,
} from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";

type RunsPage = components["schemas"]["Page_RunListItem_"];
type RunDetail = components["schemas"]["RunDetail"];
type Steps = { items: components["schemas"]["RunStepPublic"][] };
type Logs = components["schemas"]["RunLogPage"];
type Artifacts = { items: components["schemas"]["ArtifactPublic"][] };

export interface RunsSummary {
  activeNow: number;
  today: number;
  passed: number;
  failed: number;
  avgDurationMs: number;
  queue: number;
}

export interface NetworkEvent {
  method: string;
  path: string;
  status: number;
  durationMs: number;
}

export function useRunsList(limit = 50): UseSuspenseQueryResult<RunsPage> {
  return useSuspenseQuery({
    queryKey: ["runs", { limit }] as const,
    queryFn: async () => {
      const res = await api.get<RunsPage>("/runs", { params: { limit } });
      return res.data;
    },
  });
}

export function useRunsSummary(): UseSuspenseQueryResult<RunsSummary> {
  return useSuspenseQuery({
    queryKey: ["runs", "summary"] as const,
    queryFn: async () => {
      const res = await api.get<RunsSummary>("/runs/summary");
      return res.data;
    },
  });
}

export function useRun(runId: string | undefined): UseQueryResult<RunDetail> {
  return useQuery({
    queryKey: ["runs", runId] as const,
    enabled: Boolean(runId),
    queryFn: async () => {
      const res = await api.get<RunDetail>(`/runs/${runId ?? ""}`);
      return res.data;
    },
  });
}

export function useRunSteps(runId: string | undefined): UseQueryResult<Steps> {
  return useQuery({
    queryKey: ["runs", runId, "steps"] as const,
    enabled: Boolean(runId),
    queryFn: async () => {
      const res = await api.get<Steps>(`/runs/${runId ?? ""}/steps`);
      return res.data;
    },
  });
}

export function useRunLogs(runId: string | undefined): UseQueryResult<Logs> {
  return useQuery({
    queryKey: ["runs", runId, "logs"] as const,
    enabled: Boolean(runId),
    queryFn: async () => {
      const res = await api.get<Logs>(`/runs/${runId ?? ""}/logs`);
      return res.data;
    },
  });
}

export function useRunArtifacts(runId: string | undefined): UseQueryResult<Artifacts> {
  return useQuery({
    queryKey: ["runs", runId, "artifacts"] as const,
    enabled: Boolean(runId),
    queryFn: async () => {
      const res = await api.get<Artifacts>(`/runs/${runId ?? ""}/artifacts`);
      return res.data;
    },
  });
}

export function useRunNetwork(runId: string | undefined): UseQueryResult<{ items: NetworkEvent[] }> {
  return useQuery({
    queryKey: ["runs", runId, "network"] as const,
    enabled: Boolean(runId),
    queryFn: async () => {
      const res = await api.get<{ items: NetworkEvent[] }>(`/runs/${runId ?? ""}/network`);
      return res.data;
    },
  });
}

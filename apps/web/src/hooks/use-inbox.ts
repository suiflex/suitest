import { useSuspenseQuery, type UseSuspenseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

/**
 * Inbox notification kinds the UI knows how to render. Mirrors UI_SPEC § 3.12
 * — the M1a backend doesn't yet expose `/inbox`, so we model the shape locally
 * and let MSW seed test/fixture data. The full backend lands in M2.
 */
export type InboxItemKind =
  | "GATING_FAIL"
  | "FLAKY_PROMOTION"
  | "MANUAL_RUN_FAIL"
  | "MCP_HEALTH"
  | "AGENT_DEFECT_FILED"
  | "AGENT_GENERATION_DONE";

export interface InboxItem {
  id: string;
  kind: InboxItemKind;
  title: string;
  body: string;
  ref?: string | null;
  createdAt: string;
  read: boolean;
}

export interface InboxPage {
  items: InboxItem[];
  unread: number;
}

export function useInbox(status: "all" | "unread" = "all"): UseSuspenseQueryResult<InboxPage> {
  return useSuspenseQuery({
    queryKey: ["inbox", status] as const,
    queryFn: async () => {
      const res = await api.get<InboxPage>("/inbox", { params: { status } });
      return res.data;
    },
  });
}

/** Item kinds backed by deterministic signals only — visible in ZERO. */
const ZERO_SAFE_KINDS: ReadonlySet<InboxItemKind> = new Set([
  "GATING_FAIL",
  "FLAKY_PROMOTION",
  "MANUAL_RUN_FAIL",
  "MCP_HEALTH",
]);

export function isZeroSafeKind(kind: InboxItemKind): boolean {
  return ZERO_SAFE_KINDS.has(kind);
}

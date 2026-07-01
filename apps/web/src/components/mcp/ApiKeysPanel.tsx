import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { KeyRound, Trash2 } from "lucide-react";

import { CopyButton } from "@/components/shared/CopyButton";
import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type ApiKeyItem, listApiKeys, revokeApiKey } from "@/lib/api-client";

const API_KEYS_QUERY_KEY = ["api-keys"] as const;

function KeyRow({
  item,
  onRevoke,
  revoking,
}: {
  item: ApiKeyItem;
  onRevoke: (id: string) => void;
  revoking: boolean;
}): React.ReactElement {
  return (
    <div
      data-testid="api-key-row"
      className="flex items-center justify-between gap-3 rounded-md border border-border bg-bg-elev-1 px-3 py-2.5"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-bg-elev-2 text-fg-4">
          <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[12.5px] font-medium text-fg-1">{item.name}</span>
          <span className="font-mono text-[11px] text-fg-4">
            {item.key_prefix}
            <span className="text-fg-5">…</span>
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        <div className="hidden flex-col items-end sm:flex">
          <span className="font-mono text-[10.5px] text-fg-4">
            created {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
          </span>
          <span className="font-mono text-[10.5px] text-fg-5">
            {item.last_used_at
              ? `used ${formatDistanceToNow(new Date(item.last_used_at), { addSuffix: true })}`
              : "never used"}
          </span>
        </div>
        {item.key ? <CopyButton value={item.key} label={`Copy key ${item.name}`} /> : null}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-fg-4 hover:text-red"
          disabled={revoking}
          onClick={() => {
            onRevoke(item.id);
          }}
          data-testid={`revoke-key-${item.id}`}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          Revoke
        </Button>
      </div>
    </div>
  );
}

/**
 * Lists a workspace's live API keys so they survive a refresh (the plaintext is
 * only ever shown once at creation, but the key record — name, prefix, usage —
 * persists here). Revoke removes a key immediately.
 */
export function ApiKeysPanel(): React.ReactElement {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: listApiKeys,
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
    },
  });

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-2" data-testid="api-keys-loading">
        <Skeleton className="h-[52px] w-full" />
        <Skeleton className="h-[52px] w-full" />
      </div>
    );
  }

  const keys = query.data ?? [];

  if (keys.length === 0) {
    return (
      <EmptyState
        icon={KeyRound}
        title="No API keys yet"
        subtitle="Create a key with “Connect IDE” so your AI agent can reach this workspace over MCP."
      />
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="api-keys-list">
      {keys.map((k) => (
        <KeyRow
          key={k.id}
          item={k}
          revoking={revokeMutation.isPending}
          onRevoke={(id) => {
            revokeMutation.mutate(id);
          }}
        />
      ))}
    </div>
  );
}

export { API_KEYS_QUERY_KEY };

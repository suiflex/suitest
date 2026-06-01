import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createMcpProvider,
  testMcpConnection,
  updateMcpProvider,
  type McpProbeResult,
  type McpProviderDetail,
  type McpProviderWriteBody,
  type McpTransport,
} from "@/lib/api-client";

interface RegisterMcpModalProps {
  /** When set, the modal edits this provider instead of creating a new one. */
  existing?: McpProviderDetail;
  onClose: () => void;
}

const TRANSPORTS: McpTransport[] = ["stdio", "sse", "ws"];

const INPUT_CLASS =
  "h-9 rounded-md border border-border bg-bg-elev-1 px-2 text-[12.5px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40 disabled:opacity-50";

/**
 * Create / edit a custom MCP provider (M2-6). The endpoint field doubles as the
 * shell command for ``stdio`` providers and the URL for ``sse`` / ``ws``.
 * Secrets are write-only — on edit we never pre-fill them (the API never
 * returns cleartext); the blank field means "keep existing".
 */
export function RegisterMcpModal({ existing, onClose }: RegisterMcpModalProps): React.ReactElement {
  const isEdit = existing !== undefined;
  const qc = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [kind, setKind] = useState(existing?.kind ?? "custom");
  const [endpoint, setEndpoint] = useState(existing?.endpoint ?? "");
  const [transport, setTransport] = useState<McpTransport>(
    (existing?.transport as McpTransport) ?? "stdio",
  );
  const [secretsJson, setSecretsJson] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [probe, setProbe] = useState<McpProbeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  function buildBody(): McpProviderWriteBody {
    let secrets: Record<string, unknown> | undefined;
    if (secretsJson.trim() !== "") {
      secrets = JSON.parse(secretsJson) as Record<string, unknown>;
    }
    return {
      name,
      kind,
      endpoint,
      transport,
      ...(secrets ? { secretsJson: secrets } : {}),
    };
  }

  const testConn = useMutation({
    mutationFn: () => testMcpConnection(buildBody()),
    onMutate: () => {
      setProbe(null);
      setProbeError(null);
    },
    onSuccess: (result) => {
      setProbe(result);
    },
    onError: (err: unknown) => {
      setProbeError(err instanceof Error ? err.message : "Connection failed");
    },
  });

  const mutation = useMutation({
    mutationFn: async (): Promise<McpProviderDetail> => {
      const body = buildBody();
      if (isEdit && existing) {
        return updateMcpProvider(existing.id, body);
      }
      return createMcpProvider(body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-providers"] });
      onClose();
    },
    onError: (err: unknown) => {
      setFormError(err instanceof Error ? err.message : "Failed to save provider");
    },
  });

  const canSubmit = name.trim() !== "" && kind.trim() !== "" && endpoint.trim() !== "";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        data-testid="register-mcp-modal"
        className="border border-border bg-bg-elev-1 sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle className="text-fg-1">
            {isEdit ? "Edit MCP Server" : "Add Custom MCP"}
          </DialogTitle>
          <DialogDescription className="text-fg-3">
            Register an MCP server by endpoint + transport. It is connected and its tools are
            discovered on save.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setFormError(null);
            mutation.mutate();
          }}
        >
          <Field label="Name">
            <input
              data-testid="mcp-name"
              className={INPUT_CLASS}
              value={name}
              disabled={isEdit}
              onChange={(e) => {
                setName(e.target.value);
              }}
              placeholder="payments-mcp"
            />
          </Field>
          <Field label="Kind">
            <input
              data-testid="mcp-kind"
              className={INPUT_CLASS}
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
              }}
              placeholder="payments"
            />
          </Field>
          <Field label="Transport">
            <select
              data-testid="mcp-transport"
              className={INPUT_CLASS}
              value={transport}
              onChange={(e) => {
                setTransport(e.target.value as McpTransport);
              }}
            >
              {TRANSPORTS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label={transport === "stdio" ? "Command" : "Endpoint URL"}>
            <input
              data-testid="mcp-endpoint"
              className={INPUT_CLASS}
              value={endpoint}
              onChange={(e) => {
                setEndpoint(e.target.value);
              }}
              placeholder={
                transport === "stdio" ? "npx -y @acme/payments-mcp" : "https://mcp.acme.dev/sse"
              }
            />
          </Field>
          <Field label={isEdit ? "Secrets JSON (leave blank to keep)" : "Secrets JSON (optional)"}>
            <textarea
              data-testid="mcp-secrets"
              className="rounded-md border border-border bg-bg-elev-1 p-2 font-mono text-[11px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
              rows={2}
              value={secretsJson}
              onChange={(e) => {
                setSecretsJson(e.target.value);
              }}
              placeholder='{"api_key": "..."}'
            />
          </Field>

          {probe ? (
            <p
              className="rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-[12px] text-fg-1"
              data-testid="mcp-probe-ok"
            >
              Connected · discovered {probe.tools.length.toString()} tool
              {probe.tools.length === 1 ? "" : "s"}
              {probe.tools.length > 0 ? `: ${probe.tools.map((t) => t.name).join(", ")}` : ""}
            </p>
          ) : null}
          {probeError ? (
            <p className="text-[12px] text-red" data-testid="mcp-probe-error">
              {probeError}
            </p>
          ) : null}
          {formError ? (
            <p className="text-[12px] text-red" data-testid="mcp-form-error">
              {formError}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="mcp-test-connection"
              disabled={!canSubmit || testConn.isPending}
              onClick={() => {
                setFormError(null);
                testConn.mutate();
              }}
            >
              {testConn.isPending ? "Testing…" : "Test connection"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              data-testid="mcp-submit"
              disabled={!canSubmit || mutation.isPending}
            >
              {mutation.isPending ? "Saving…" : isEdit ? "Save changes" : "Register"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-fg-3">{label}</span>
      {children}
    </label>
  );
}

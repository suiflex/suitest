import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  cancelChatGptLogin,
  type ChatGptCredentialMode,
  type ChatGptLoginStart,
  finishChatGptLogin,
  pollChatGptLogin,
  startChatGptLogin,
} from "@/lib/api-client";

/** Keep the friendly sentence, but say what actually came back — a sign-in that
 *  fails because the route is missing reads exactly like a rejected credential
 *  otherwise. */
function loginError(fallback: string, err: unknown): string {
  if (!(err instanceof ApiError)) return fallback;
  const detail = err.message.trim();
  return detail ? `${fallback} (${err.status}: ${detail})` : `${fallback} (${err.status})`;
}

/** Sign in with ChatGPT: start a flow, wait for approval, then store it.
 *
 * The transport is the server's call — the browser redirect only lands when the
 * person clicking is on the API's own machine — so this renders whichever of the
 * two it hands back.
 */
export function ChatGptSignIn({
  workspaceId,
  onDone,
}: {
  workspaceId: string;
  onDone: () => void;
}): React.ReactElement {
  const [flow, setFlow] = useState<ChatGptLoginStart | null>(null);
  const [credentialMode, setCredentialMode] = useState<ChatGptCredentialMode>("api_key");
  const [model, setModel] = useState("");
  const [error, setError] = useState<string | null>(null);

  const startMutation = useMutation({
    mutationFn: () => startChatGptLogin(workspaceId),
    onSuccess: (started) => {
      setError(null);
      setFlow(started);
      if (started.authorizeUrl) window.open(started.authorizeUrl, "_blank", "noopener");
    },
    onError: (err) => setError(loginError("Could not start the sign-in.", err)),
  });

  const statusQuery = useQuery({
    queryKey: ["chatgpt-login", workspaceId, flow?.flowId] as const,
    queryFn: () => (flow ? pollChatGptLogin(workspaceId, flow.flowId) : null),
    enabled: flow !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? (flow?.intervalS ?? 5) * 1000 : false,
  });

  const finishMutation = useMutation({
    mutationFn: () =>
      flow
        ? finishChatGptLogin(workspaceId, flow.flowId, { credentialMode, model })
        : Promise.reject(new Error("no sign-in in progress")),
    onSuccess: () => {
      setFlow(null);
      onDone();
    },
    onError: (err) => setError(loginError("Could not save the signed-in credential.", err)),
  });

  const cancel = (): void => {
    if (flow) void cancelChatGptLogin(workspaceId, flow.flowId);
    setFlow(null);
    setError(null);
  };

  const status = statusQuery.data?.status;

  return (
    <section
      className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5"
      data-testid="chatgpt-signin"
    >
      <p className="text-[12.5px] text-fg-3">
        Authenticate with your ChatGPT account instead of a key. Suitest stores the resulting
        credential encrypted and refreshes it for you. The sign-in uses the Codex CLI&apos;s public
        OAuth client, since OpenAI publishes no separate one for third-party apps.
      </p>

      {flow === null ? (
        <button
          type="button"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
          className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
          data-testid="chatgpt-signin-start"
        >
          {startMutation.isPending ? "Starting…" : "Sign in with ChatGPT"}
        </button>
      ) : null}

      {flow !== null && status !== "ready" ? (
        <div className="space-y-2 text-[13px] text-fg-1" data-testid="chatgpt-signin-pending">
          {flow.mode === "device" ? (
            <>
              <p>
                Open{" "}
                <a
                  href={flow.verificationUrl ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  {flow.verificationUrl}
                </a>{" "}
                and enter this code:
              </p>
              <p className="font-mono text-[18px] tracking-widest text-fg-1">{flow.userCode}</p>
            </>
          ) : (
            <p>Approve the sign-in in the tab that just opened, then come back here.</p>
          )}
          <p className="text-[12px] text-fg-4">
            {status === "error"
              ? (statusQuery.data?.message ?? "The sign-in failed.")
              : "Waiting for approval… the code expires in 15 minutes."}
          </p>
          <button
            type="button"
            onClick={cancel}
            className="text-[12.5px] text-fg-3 hover:underline"
            data-testid="chatgpt-signin-cancel"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {flow !== null && status === "ready" ? (
        <div className="space-y-3" data-testid="chatgpt-signin-ready">
          <p className="text-[13px] text-accent">
            Signed in{statusQuery.data?.account ? ` as ${statusQuery.data.account}` : ""}.
          </p>

          <div className="space-y-2">
            <span className="text-[12.5px] font-medium text-fg-1">Use this sign-in for</span>
            {(
              [
                ["api_key", "An API key from my account (billed at API rates)"],
                ["subscription", "My ChatGPT plan (no API billing) — experimental"],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-[13px] text-fg-1">
                <input
                  type="radio"
                  name="chatgpt-credential-mode"
                  value={value}
                  checked={credentialMode === value}
                  onChange={() => setCredentialMode(value)}
                  className="accent-accent"
                />
                {label}
              </label>
            ))}
          </div>

          <div className="space-y-2">
            <label htmlFor="chatgpt-model" className="text-[12.5px] font-medium text-fg-1">
              Model
            </label>
            <input
              id="chatgpt-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-5.6"
              required
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            />
          </div>

          <button
            type="button"
            onClick={() => finishMutation.mutate()}
            disabled={finishMutation.isPending || !model}
            className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
            data-testid="chatgpt-signin-finish"
          >
            {finishMutation.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
        >
          {error}
        </p>
      ) : null}
    </section>
  );
}

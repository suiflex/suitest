import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  cancelGoogleLogin,
  fetchGoogleProjects,
  finishGoogleLogin,
  type GoogleLoginStart,
  pollGoogleLogin,
  startGoogleLogin,
  submitGoogleCallback,
} from "@/lib/api-client";

/** Vertex regions worth offering; any other is typed in. */
const LOCATIONS = [
  "us-central1",
  "us-east4",
  "europe-west4",
  "asia-southeast1",
  "asia-northeast1",
] as const;

function loginError(fallback: string, err: unknown): string {
  return err instanceof ApiError && err.message ? err.message : fallback;
}

/** Sign in with Google, storing the result as a `google-vertex` config.
 *
 * Which transport to use is the server's call. On the API's own machine the
 * redirect lands on a loopback listener and this just polls. Anywhere else it
 * cannot, and Google's device flow is not available for the `cloud-platform`
 * scope, so the user pastes the URL the browser ended up on.
 */
export function GoogleSignIn({
  workspaceId,
  onDone,
}: {
  workspaceId: string;
  onDone: () => void;
}): React.ReactElement {
  const [flow, setFlow] = useState<GoogleLoginStart | null>(null);
  const [pastedUrl, setPastedUrl] = useState("");
  const [pasteAccepted, setPasteAccepted] = useState(false);
  const [model, setModel] = useState("google/gemini-2.5-pro");
  const [project, setProject] = useState("");
  const [location, setLocation] = useState<string>(LOCATIONS[0]);
  const [error, setError] = useState<string | null>(null);

  const startMutation = useMutation({
    mutationFn: () => startGoogleLogin(workspaceId),
    onSuccess: (started) => {
      setError(null);
      setPasteAccepted(false);
      setPastedUrl("");
      setFlow(started);
      if (started.authorizeUrl) window.open(started.authorizeUrl, "_blank", "noopener");
    },
    onError: (err) => setError(loginError("Could not start the sign-in.", err)),
  });

  // Only browser mode has a listener to wait on; paste mode advances when the
  // user submits, so polling it would just be noise.
  const isPolling = flow !== null && flow.mode === "browser";
  const statusQuery = useQuery({
    queryKey: ["google-login", workspaceId, flow?.flowId] as const,
    queryFn: () => (flow ? pollGoogleLogin(workspaceId, flow.flowId) : null),
    enabled: isPolling,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? (flow?.intervalS ?? 2) * 1000 : false,
  });

  const pasteMutation = useMutation({
    mutationFn: () =>
      flow
        ? submitGoogleCallback(workspaceId, flow.flowId, pastedUrl)
        : Promise.reject(new Error("no sign-in in progress")),
    onSuccess: () => {
      setError(null);
      setPasteAccepted(true);
    },
    onError: (err) => setError(loginError("That URL could not be used.", err)),
  });

  const finishMutation = useMutation({
    mutationFn: () =>
      flow
        ? finishGoogleLogin(workspaceId, flow.flowId, {
            model,
            gcpProject: project,
            gcpLocation: location,
          })
        : Promise.reject(new Error("no sign-in in progress")),
    onSuccess: () => {
      setFlow(null);
      onDone();
    },
    onError: (err) => setError(loginError("Could not save the signed-in credential.", err)),
  });

  const cancel = (): void => {
    if (flow) void cancelGoogleLogin(workspaceId, flow.flowId);
    setFlow(null);
    setPasteAccepted(false);
    setPastedUrl("");
    setError(null);
  };

  const ready = pasteAccepted || statusQuery.data?.status === "ready";
  const projectsQuery = useQuery({
    queryKey: ["google-projects", workspaceId, flow?.flowId] as const,
    queryFn: () => (flow ? fetchGoogleProjects(workspaceId, flow.flowId) : []),
    enabled: ready && flow !== null,
    // An unreadable list is an answer, not something to keep asking for.
    retry: false,
  });
  const projects = projectsQuery.data ?? [];

  const status = pasteAccepted ? "ready" : statusQuery.data?.status;
  const email = pasteMutation.data?.email ?? statusQuery.data?.email;

  return (
    <section
      className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5"
      data-testid="google-signin"
    >
      <p className="text-[12.5px] text-fg-3">
        Authenticate with your Google account instead of a key. Suitest calls Vertex AI as you,
        stores the credential encrypted and refreshes it for you. Your Google Cloud project needs
        the Vertex AI API enabled and billing active.
      </p>

      {flow === null ? (
        <button
          type="button"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
          className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
          data-testid="google-signin-start"
        >
          {startMutation.isPending ? "Starting…" : "Sign in with Google"}
        </button>
      ) : null}

      {flow !== null && status !== "ready" ? (
        <div className="space-y-2 text-[13px] text-fg-1" data-testid="google-signin-pending">
          {flow.mode === "paste" ? (
            <>
              <p>
                Approve the sign-in in the tab that just opened. Your browser will land on a{" "}
                <code className="font-mono text-[12px] text-fg-3">127.0.0.1</code> page that cannot
                load — that is expected. Copy its full address and paste it here.
              </p>
              <input
                value={pastedUrl}
                onChange={(e) => setPastedUrl(e.target.value)}
                placeholder="http://127.0.0.1:8765/?state=…&code=…"
                aria-label="Callback URL"
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 font-mono text-[12px] text-fg-1 outline-none focus:border-accent"
                data-testid="google-signin-callback-url"
              />
              <button
                type="button"
                onClick={() => pasteMutation.mutate()}
                disabled={pasteMutation.isPending || pastedUrl.trim() === ""}
                className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
                data-testid="google-signin-submit-url"
              >
                {pasteMutation.isPending ? "Checking…" : "Continue"}
              </button>
            </>
          ) : (
            <p>Approve the sign-in in the tab that just opened, then come back here.</p>
          )}
          <p className="text-[12px] text-fg-4">
            {status === "error"
              ? (statusQuery.data?.message ?? "The sign-in failed.")
              : "The sign-in expires in 15 minutes."}
          </p>
          <button
            type="button"
            onClick={cancel}
            className="text-[12.5px] text-fg-3 hover:underline"
            data-testid="google-signin-cancel"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {flow !== null && status === "ready" ? (
        <div className="space-y-3" data-testid="google-signin-ready">
          <p className="text-[13px] text-accent">Signed in{email ? ` as ${email}` : ""}.</p>

          <div className="space-y-2">
            <label htmlFor="google-project" className="text-[12.5px] font-medium text-fg-1">
              Google Cloud project
            </label>
            {projectsQuery.isLoading ? (
              <p className="text-[12.5px] text-fg-3">Looking up your projects…</p>
            ) : projects.length > 0 ? (
              <select
                id="google-project"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                required
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
                data-testid="google-signin-project-select"
              >
                <option value="">Select a project…</option>
                {projects.map((p) => (
                  <option key={p.projectId} value={p.projectId}>
                    {p.name === p.projectId ? p.projectId : `${p.name} (${p.projectId})`}
                  </option>
                ))}
              </select>
            ) : (
              <>
                {/* The list can be unreadable — Resource Manager off, or no
                    permission — and the sign-in is still good, so ask. */}
                <input
                  id="google-project"
                  autoComplete="off"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  placeholder="my-project-123"
                  required
                  className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
                  data-testid="google-signin-project-input"
                />
                <p className="text-[11.5px] text-fg-4">
                  We could not read your project list. Enter the project ID from the Google Cloud
                  console.
                </p>
              </>
            )}
          </div>

          <details className="rounded-md border border-border px-3 py-2">
            <summary className="cursor-pointer text-[12.5px] text-fg-3">Advanced</summary>
            <div className="mt-3 space-y-2">
              <label htmlFor="google-location" className="text-[12.5px] font-medium text-fg-1">
                Region
              </label>
              <input
                id="google-location"
                list="google-locations"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                required
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
              />
              <datalist id="google-locations">
                {LOCATIONS.map((loc) => (
                  <option key={loc} value={loc} />
                ))}
              </datalist>
            </div>
          </details>

          <div className="space-y-2">
            <label htmlFor="google-model" className="text-[12.5px] font-medium text-fg-1">
              Model
            </label>
            <input
              id="google-model"
              autoComplete="off"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="google/gemini-2.5-pro"
              required
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            />
          </div>

          <button
            type="button"
            onClick={() => finishMutation.mutate()}
            disabled={finishMutation.isPending || !model || !project || !location}
            className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
            data-testid="google-signin-finish"
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

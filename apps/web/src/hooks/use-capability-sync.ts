import { useWorkspaceStream } from "@/lib/ws-client";
import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Refetch the capabilities store whenever the backend publishes
 * `capability.changed` on the active workspace's channel.
 *
 * This is the propagation seam that keeps the header badge, `<Gated>`
 * surfaces, and autonomy UI in sync the instant the LLM connection state
 * changes — from this tab (settings save, header quick-test, OAuth finish)
 * or from another client — with no page refresh and no duplicated state.
 * The backend capabilities snapshot stays the single source of truth; this
 * hook only triggers a refetch of it.
 */
export function useCapabilitySync(): void {
  useWorkspaceStream((e) => {
    if (e.event === "capability.changed") {
      void useCapabilities.getState().fetch();
    }
  });
}

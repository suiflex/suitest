import type { ReactNode } from "react";

import { useFeatureEnabled } from "@/hooks/use-feature-enabled";
import type { FeatureKey } from "@/stores/use-capabilities";

interface GatedProps {
  feature: FeatureKey;
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * Render `children` only when the named capability feature is enabled in the
 * current tier. Otherwise render `fallback` (default `null`).
 *
 * Usage:
 * ```tsx
 * <Gated feature="ai_generation" fallback={<DisabledPlaceholder reason="…" />}>
 *   <GenerateButton />
 * </Gated>
 * ```
 */
export function Gated({ feature, fallback = null, children }: GatedProps): ReactNode {
  const enabled = useFeatureEnabled(feature);
  return enabled ? <>{children}</> : <>{fallback}</>;
}

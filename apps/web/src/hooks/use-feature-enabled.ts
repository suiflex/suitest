import {
  useCapabilities,
  type CapabilityFeatures,
  type FeatureKey,
} from "@/stores/use-capabilities";

/**
 * Backend feature flags returned in `capabilities.features`. Kept in sync with
 * `CapabilityFeatures` in the store (CAPABILITY_TIERS.md § 10).
 */
const DIRECT_FEATURE_KEYS: ReadonlySet<string> = new Set([
  "manual_tcm",
  "deterministic_runner",
  "deterministic_generator_openapi",
  "deterministic_generator_recorder",
  "deterministic_generator_crawler",
  "ai_generation",
  "ai_execution_agentic",
  "ai_diagnose",
  "ai_conversation",
  "semantic_search",
  "fts_search",
  "auto_defect_filing_ai",
  "auto_defect_filing_rule",
] satisfies Array<keyof CapabilityFeatures>);

/**
 * Returns `true` if the named feature is enabled in the current capabilities
 * snapshot. Direct flags map 1:1 onto `capabilities.features.*`; derived flags
 * are computed from autonomy / aggregate state.
 *
 * Returns `false` while capabilities are still loading or unavailable — this
 * makes ZERO-tier the safe default and keeps AI surfaces hidden until proven
 * otherwise.
 */
export function useFeatureEnabled(feature: FeatureKey): boolean {
  return useCapabilities((state) => {
    const caps = state.capabilities;
    if (!caps) return false;

    // Defense-in-depth: if `features` / `autonomy` are missing (malformed
    // response, partial mock, etc.), degrade to "feature disabled" instead of
    // throwing. ZERO is the safe default.
    if (DIRECT_FEATURE_KEYS.has(feature)) {
      return Boolean(caps.features?.[feature as keyof CapabilityFeatures]);
    }

    if (feature === "ai_panel") {
      return Boolean(caps.features?.ai_conversation || caps.features?.ai_generation);
    }
    if (feature === "autonomy_assist") {
      return caps.autonomy?.available?.includes("assist") ?? false;
    }
    if (feature === "autonomy_semi_auto") {
      return caps.autonomy?.available?.includes("semi_auto") ?? false;
    }
    if (feature === "autonomy_auto") {
      return caps.autonomy?.available?.includes("auto") ?? false;
    }
    return false;
  });
}

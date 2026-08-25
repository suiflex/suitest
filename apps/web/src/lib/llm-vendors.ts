/** The LLM vendors a workspace can configure, and how to name them back.
 *
 * A vendor is what the user picks; a *provider key* is what the backend stores.
 * They are not the same, because one vendor can be reached more than one way:
 * OpenAI answers to a pasted key (`openai`) or to signing in with ChatGPT
 * (`chatgpt`), and Google to an AI Studio key (`gemini`) or to signing in and
 * calling Vertex (`google-vertex`).
 *
 * Splitting those into separate rows in the picker would make the user learn
 * which endpoint they want before they can pick who they are buying from, so
 * the picker asks for the vendor and the auth choice sits underneath it.
 *
 * The backend's own list is authoritative for what is *accepted*
 * (`apps/api/src/suitest_api/services/llm_config_service.py`); this table only
 * decides what is *offered* and how it reads.
 */

export type VendorGroup = "cloud" | "local" | "other";

export interface Vendor {
  /** `<option>` value. Not necessarily a provider key. */
  id: string;
  label: string;
  group: VendorGroup;
  /** Provider key stored when the user authenticates with a pasted key. */
  apiKeyProvider: string;
  /** Present only when this vendor can also be reached by signing in. */
  oauth?: {
    label: string;
    /** Which sign-in flow drives it — the panel maps this to a component. */
    flow: "chatgpt" | "google" | "antigravity";
  };
  /** The user must supply the endpoint; there is no default to fall back to. */
  needsBaseUrl?: boolean;
  /** No API key field: the endpoint is unauthenticated or uses ambient creds. */
  keyless?: boolean;
  /** Reachable only by signing in — there is no key to paste for this one. */
  oauthOnly?: boolean;
}

export const VENDORS: readonly Vendor[] = [
  {
    id: "anthropic",
    label: "Anthropic",
    group: "cloud",
    apiKeyProvider: "anthropic",
  },
  {
    id: "openai",
    label: "OpenAI",
    group: "cloud",
    apiKeyProvider: "openai",
    oauth: { label: "Sign in with ChatGPT", flow: "chatgpt" },
  },
  {
    id: "google",
    label: "Google",
    group: "cloud",
    // A pasted key is an AI Studio key, which talks to the Gemini API.
    apiKeyProvider: "gemini",
    oauth: { label: "Sign in with Google", flow: "google" },
  },
  {
    id: "antigravity",
    label: "Antigravity",
    group: "cloud",
    // No key path: this product is only reachable by signing in.
    apiKeyProvider: "antigravity",
    oauth: { label: "Sign in with Google", flow: "antigravity" },
    keyless: true,
    oauthOnly: true,
  },
  { id: "groq", label: "Groq", group: "cloud", apiKeyProvider: "groq" },
  { id: "openrouter", label: "OpenRouter", group: "cloud", apiKeyProvider: "openrouter" },
  { id: "deepseek", label: "DeepSeek", group: "cloud", apiKeyProvider: "deepseek" },

  {
    id: "ollama",
    label: "Ollama",
    group: "local",
    apiKeyProvider: "ollama",
    needsBaseUrl: true,
    keyless: true,
  },
  {
    id: "llamacpp",
    label: "llama.cpp",
    group: "local",
    apiKeyProvider: "llamacpp",
    needsBaseUrl: true,
    keyless: true,
  },
  {
    id: "vllm",
    label: "vLLM",
    group: "local",
    apiKeyProvider: "vllm",
    needsBaseUrl: true,
    keyless: true,
  },
  {
    id: "lmstudio",
    label: "LM Studio",
    group: "local",
    apiKeyProvider: "lmstudio",
    needsBaseUrl: true,
    keyless: true,
  },

  {
    id: "custom",
    label: "Custom (OpenAI-compatible URL)",
    group: "other",
    apiKeyProvider: "custom",
    needsBaseUrl: true,
  },
];

export function vendorById(id: string): Vendor | undefined {
  return VENDORS.find((v) => v.id === id);
}

export function vendorsInGroup(group: VendorGroup): Vendor[] {
  return VENDORS.filter((v) => v.group === group);
}

/** Provider keys only ever produced by a sign-in, so never offered in the picker. */
const OAUTH_ONLY_LABELS: Record<string, string> = {
  chatgpt: "OpenAI (ChatGPT plan)",
  "google-vertex": "Google (Vertex AI)",
  "google-codeassist": "Google (Code Assist)",
};

/** Provider keys the backend accepts but this build does not offer in the picker. */
const UNLISTED_LABELS: Record<string, string> = {
  azure: "Azure OpenAI",
  bedrock: "AWS Bedrock",
  vertex: "Vertex AI (service account)",
  mock: "Mock (test provider)",
};

/** How to write a stored provider key where a person will read it.
 *
 * Every surface used to print the raw key, so a workspace that signed in with
 * Google was told it was running `google-vertex` — an internal name that only
 * means something to this codebase. Unknown keys fall through unchanged rather
 * than being hidden: a provider we forgot to name is still better shown than
 * swallowed.
 */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return "—";
  const key = provider.trim().toLowerCase();
  return (
    OAUTH_ONLY_LABELS[key] ??
    UNLISTED_LABELS[key] ??
    VENDORS.find((v) => v.apiKeyProvider === key)?.label ??
    provider
  );
}

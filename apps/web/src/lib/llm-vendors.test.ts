import { describe, expect, it } from "vitest";

import { providerLabel, VENDORS, vendorById, vendorsInGroup } from "@/lib/llm-vendors";

describe("llm-vendors", () => {
  it("names the provider keys a sign-in produces, which are never in the picker", () => {
    // These are the ones that leaked internal names into the UI.
    expect(providerLabel("google-vertex")).toBe("Google (Vertex AI)");
    expect(providerLabel("chatgpt")).toBe("OpenAI (ChatGPT plan)");
    // Neither is offered as a vendor — you arrive at them by signing in.
    expect(VENDORS.some((v) => v.id === "google-vertex" || v.id === "chatgpt")).toBe(false);
  });

  it("names the providers a pasted key produces", () => {
    expect(providerLabel("gemini")).toBe("Google");
    expect(providerLabel("openai")).toBe("OpenAI");
    expect(providerLabel("anthropic")).toBe("Anthropic");
    expect(providerLabel("llamacpp")).toBe("llama.cpp");
  });

  it("names backend providers this build does not offer", () => {
    expect(providerLabel("bedrock")).toBe("AWS Bedrock");
    expect(providerLabel("vertex")).toBe("Vertex AI (service account)");
  });

  it("passes an unknown provider through rather than hiding it", () => {
    // A provider we forgot to name is still better shown than swallowed.
    expect(providerLabel("some-future-provider")).toBe("some-future-provider");
  });

  it("renders an absent provider as a dash", () => {
    expect(providerLabel(null)).toBe("—");
    expect(providerLabel(undefined)).toBe("—");
    expect(providerLabel("")).toBe("—");
  });

  it("is case- and whitespace-insensitive", () => {
    expect(providerLabel("  Google-Vertex  ")).toBe("Google (Vertex AI)");
  });

  it("offers exactly two vendors that can be signed in to", () => {
    const withOauth = VENDORS.filter((v) => v.oauth);
    expect(withOauth.map((v) => v.id).sort()).toEqual(["google", "openai"]);
    expect(vendorById("openai")?.oauth?.flow).toBe("chatgpt");
    expect(vendorById("google")?.oauth?.flow).toBe("google");
  });

  it("marks every local vendor as needing a base url and no key", () => {
    const local = vendorsInGroup("local");
    expect(local.length).toBeGreaterThan(0);
    for (const v of local) {
      expect(v.needsBaseUrl).toBe(true);
      expect(v.keyless).toBe(true);
    }
  });

  it("gives every vendor a unique id and a provider key", () => {
    const ids = VENDORS.map((v) => v.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const v of VENDORS) expect(v.apiKeyProvider).toBeTruthy();
  });
});

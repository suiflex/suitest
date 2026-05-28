import { afterEach, describe, expect, it } from "vitest";

import i18n from "./i18n";

/**
 * Smoke test for the i18n wiring (Task 12.4). We don't assert the whole
 * dictionary — that's a copy review. Instead we prove the plumbing:
 *  - English is the default language.
 *  - Switching to `id` resolves the same key to its Bahasa Indonesia value.
 */
describe("i18n", () => {
  afterEach(async () => {
    // Reset for the next test so language order doesn't leak.
    await i18n.changeLanguage("en");
  });

  it("defaults to English", () => {
    expect(i18n.language).toBe("en");
    expect(i18n.t("dashboard.title")).toBe("Dashboard");
  });

  it("returns Bahasa Indonesia translations after changeLanguage('id')", async () => {
    await i18n.changeLanguage("id");
    expect(i18n.t("dashboard.title")).toBe("Dasbor");
    expect(i18n.t("runs.title")).toBe("Eksekusi");
    expect(i18n.t("defects.title")).toBe("Defek");
  });

  it("falls back to English for unknown languages", async () => {
    await i18n.changeLanguage("xx");
    expect(i18n.t("dashboard.title")).toBe("Dashboard");
  });
});

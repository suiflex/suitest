import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api-types";
import {
  deriveCaseType,
  deriveServerStep,
  deriveStepType,
  displayTitle,
  generateFallbackSteps,
  humanizeTestTitle,
  looksLikeSlug,
  technicalKey,
} from "@/lib/test-case-format";

type TestStepPublic = components["schemas"]["TestStepPublic"];

function step(partial: Partial<TestStepPublic>): TestStepPublic {
  return {
    id: "s1",
    case_id: "c1",
    order: 1,
    action: "Do a thing",
    expected: "It works",
    code: null,
    data: null,
    executable: false,
    mcp_provider: "playwright-mcp",
    target_kind: "FE_WEB",
    ...partial,
  };
}

describe("humanizeTestTitle", () => {
  it("turns a snake_case slug into a sentence-case title", () => {
    expect(humanizeTestTitle("successful_login_opens_the_dashboard")).toBe(
      "Successful login opens the dashboard",
    );
    expect(humanizeTestTitle("invalid_login_shows_an_error")).toBe("Invalid login shows an error");
    expect(humanizeTestTitle("protected_route_redirects_anonymous_user")).toBe(
      "Protected route redirects anonymous user",
    );
  });

  it("upper-cases known acronyms", () => {
    expect(humanizeTestTitle("create_product_via_api")).toBe("Create product via API");
  });
});

describe("looksLikeSlug / displayTitle / technicalKey", () => {
  it("detects slugs but not human titles", () => {
    expect(looksLikeSlug("successful_login_opens_the_dashboard")).toBe(true);
    expect(looksLikeSlug("POST /users — contract")).toBe(false);
    expect(looksLikeSlug("Already A Title")).toBe(false);
  });

  it("humanizes slugs and leaves real titles untouched", () => {
    expect(displayTitle("invalid_login_shows_an_error")).toBe("Invalid login shows an error");
    expect(displayTitle("POST /users — contract")).toBe("POST /users — contract");
  });

  it("exposes the raw slug as a technical key only when it is a slug", () => {
    expect(technicalKey("invalid_login_shows_an_error")).toBe("invalid_login_shows_an_error");
    expect(technicalKey("POST /users — contract")).toBeNull();
  });
});

describe("deriveStepType", () => {
  it("classifies by wording", () => {
    expect(deriveStepType("Navigate to /login")).toBe("navigation");
    expect(deriveStepType("Fill email and password")).toBe("action");
    expect(deriveStepType("Dashboard page is visible")).toBe("assertion");
    expect(deriveStepType("Wait for the toast")).toBe("wait");
  });

  it("classifies backend target kinds as api", () => {
    expect(deriveStepType("Fill body", "BE_REST")).toBe("api");
  });
});

describe("deriveServerStep", () => {
  it("keeps a real expected but derives one when it echoes the action", () => {
    const withExpected = deriveServerStep(step({ action: "Click Sign In", expected: "Logged in" }));
    expect(withExpected.expected).toBe("Logged in");

    const redundant = deriveServerStep(
      step({ action: "Click Sign In", expected: "Click Sign In" }),
    );
    expect(redundant.expected).toBe("Step completes successfully.");

    const assertion = deriveServerStep(
      step({ action: "Dashboard is visible", expected: "Dashboard is visible" }),
    );
    expect(assertion.type).toBe("assertion");
    expect(assertion.expected).toBe("Dashboard is visible");
  });
});

describe("deriveCaseType", () => {
  it("prefers e2e when any FE_WEB step exists", () => {
    expect(deriveCaseType([step({ target_kind: "FE_WEB" })])).toBe("e2e");
    expect(deriveCaseType([step({ target_kind: "BE_REST" })])).toBe("api");
    expect(deriveCaseType([])).toBe("e2e");
  });
});

describe("generateFallbackSteps", () => {
  it("never returns an empty list and never uses a bare id as title", () => {
    for (const key of [
      "successful_login_opens_the_dashboard",
      "products_list_loads_after_login",
      "search_with_no_match_shows_empty_state",
      "some_unknown_scenario",
    ]) {
      const steps = generateFallbackSteps(key);
      expect(steps.length).toBeGreaterThan(0);
      for (const s of steps) {
        expect(s.title.trim().length).toBeGreaterThan(0);
        expect(s.title).not.toMatch(/^TC-\d+$/);
        expect(s.instruction.trim().length).toBeGreaterThan(0);
        expect(s.expected.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("builds login + dashboard verification for a login-dashboard slug", () => {
    const steps = generateFallbackSteps("successful_login_opens_the_dashboard");
    expect(steps.some((s) => s.type === "navigation")).toBe(true);
    expect(steps.some((s) => s.type === "assertion")).toBe(true);
  });

  it("shows an empty-state expectation for a no-match search", () => {
    const steps = generateFallbackSteps("search_with_no_match_shows_empty_state");
    const assertion = steps.find((s) => s.type === "assertion");
    expect(assertion?.expected.toLowerCase()).toContain("empty");
  });
});

/**
 * Presentation helpers for test cases + steps.
 *
 * Backend cases carry only a technical ``name`` (which for MCP/lifecycle-
 * published cases is a slug like ``successful_login_opens_the_dashboard``) plus
 * a ``public_id`` (the human-facing code, e.g. ``TC-1036``). Steps carry only
 * ``action`` / ``expected`` / ``target_kind`` — no ``type``, ``title`` or
 * ``status``. QA needs readable titles, a step ``type`` badge, and a clean
 * instruction/expected split, so this module derives all of that on the client.
 *
 * These are pure functions with no React/DOM deps so they can be unit-tested in
 * isolation (see test-case-format.test.ts).
 */

import type { components } from "@/lib/api-types";

type TestStepPublic = components["schemas"]["TestStepPublic"];
type TargetKind = components["schemas"]["TargetKind"];

/** Frontend-facing step type (mirrors TestSprite's step taxonomy). */
export type StepType = "navigation" | "action" | "assertion" | "wait" | "api";

/** Frontend-facing case type derived from a case's step target kinds. */
export type CaseType = "frontend" | "backend" | "api" | "e2e";

/** A derived, presentation-ready step. Independent of whether it came from the
 *  server or a fallback generator. */
export interface DerivedStep {
  id: string;
  order: number;
  title: string;
  type: StepType;
  instruction: string;
  expected: string;
  /** Executable per the workspace tier (server steps only; fallback = false). */
  executable: boolean;
  /** Optional pointers surfaced as small metadata. */
  mcpProvider?: string;
  targetKind?: TargetKind;
}

// ---------------------------------------------------------------------------
// Title humanization
// ---------------------------------------------------------------------------

/** Tokens that read better fully upper-cased when they stand alone. */
const ACRONYMS = new Set(["api", "url", "id", "ui", "ux", "http", "sql", "ok", "sso", "mcp"]);

/**
 * Turn a slug / snake_case / kebab-case key into a readable sentence-case title.
 *
 *   ``successful_login_opens_the_dashboard`` → ``Successful login opens the dashboard``
 *   ``invalid_login_shows_an_error``         → ``Invalid login shows an error``
 *
 * Sentence case (only the first word is capitalized) is used rather than Title
 * Case because it reads more naturally for full sentences, which is what these
 * slugs are. Known acronyms are still upper-cased.
 */
export function humanizeTestTitle(value: string): string {
  const words = value
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter((w) => w.length > 0);
  if (words.length === 0) return value.trim();

  const out = words.map((word, i) => {
    const lower = word.toLowerCase();
    if (ACRONYMS.has(lower)) return lower.toUpperCase();
    if (i === 0) return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    return lower;
  });
  return out.join(" ");
}

/**
 * Heuristic: does this string look like a technical slug rather than an already
 * human-written title? True when it has separators (``_``/``-``) and no spaces,
 * so we only humanize keys and leave real titles (``POST /users — contract``)
 * untouched.
 */
export function looksLikeSlug(value: string): boolean {
  const v = value.trim();
  if (v.length === 0) return false;
  if (/\s/.test(v)) return false;
  return /[_-]/.test(v);
}

/** The title to render as the case's primary heading. */
export function displayTitle(name: string): string {
  return looksLikeSlug(name) ? humanizeTestTitle(name) : name;
}

/** The raw technical key to surface as small metadata (null if it's already a
 *  human title, i.e. nothing extra to show). */
export function technicalKey(name: string): string | null {
  return looksLikeSlug(name) ? name.trim() : null;
}

// ---------------------------------------------------------------------------
// Step type derivation
// ---------------------------------------------------------------------------

const NAV_RE = /\b(navigate|open|go to|goto|visit|load|browse|redirect|land on)\b/i;
const WAIT_RE = /\b(wait|pause|sleep|delay)\b/i;
const ASSERT_RE =
  /\b(assert|verify|check|expect|should|ensure|confirm|is visible|is shown|is displayed|is rendered|contains|returns|stays|remains|see|shows)\b/i;

/** Derive a step's type from its target kind + action wording. */
export function deriveStepType(action: string, targetKind?: TargetKind | null): StepType {
  if (targetKind === "BE_REST" || targetKind === "BE_GRAPHQL" || targetKind === "BE_GRPC") {
    return "api";
  }
  const a = action ?? "";
  if (NAV_RE.test(a)) return "navigation";
  if (WAIT_RE.test(a)) return "wait";
  if (ASSERT_RE.test(a)) return "assertion";
  return "action";
}

const STEP_TYPE_LABEL: Record<StepType, string> = {
  navigation: "Navigation",
  action: "Action",
  assertion: "Assertion",
  wait: "Wait",
  api: "API",
};

export function stepTypeLabel(type: StepType): string {
  return STEP_TYPE_LABEL[type];
}

/**
 * Build a presentation-ready step from a server ``TestStepPublic``.
 *
 * Publish/import paths sometimes store ``expected === action`` (a redundant
 * placeholder). We detect that and derive a sensible expectation instead of
 * echoing the instruction: assertions treat the action as the expectation,
 * everything else gets a generic "completes successfully".
 */
export function deriveServerStep(step: TestStepPublic): DerivedStep {
  const type = deriveStepType(step.action, step.target_kind);
  const action = step.action.trim();
  const rawExpected = (step.expected ?? "").trim();
  const hasRealExpected = rawExpected.length > 0 && rawExpected !== action;

  let expected: string;
  if (hasRealExpected) {
    expected = rawExpected;
  } else if (type === "assertion") {
    expected = action;
  } else {
    expected = "Step completes successfully.";
  }

  return {
    id: step.id,
    order: step.order,
    title: action,
    type,
    instruction: action,
    expected,
    executable: step.executable,
    mcpProvider: step.mcp_provider,
    targetKind: step.target_kind,
  };
}

// ---------------------------------------------------------------------------
// Case type
// ---------------------------------------------------------------------------

/** Roll a case's step target kinds up into a single case-level type badge. */
export function deriveCaseType(steps: readonly TestStepPublic[]): CaseType {
  const kinds = steps.map((s) => s.target_kind);
  if (kinds.includes("FE_WEB")) return "e2e";
  if (kinds.includes("FE_MOBILE")) return "frontend";
  if (kinds.some((k) => k === "BE_REST" || k === "BE_GRAPHQL" || k === "BE_GRPC")) return "api";
  if (kinds.some((k) => k === "DATA" || k === "INFRA")) return "backend";
  return "e2e";
}

const CASE_TYPE_LABEL: Record<CaseType, string> = {
  frontend: "Frontend",
  backend: "Backend",
  api: "API",
  e2e: "E2E",
};

export function caseTypeLabel(type: CaseType): string {
  return CASE_TYPE_LABEL[type];
}

// ---------------------------------------------------------------------------
// Fallback step generator
// ---------------------------------------------------------------------------

type FallbackSpec = Omit<DerivedStep, "id" | "order" | "executable">;

function fallback(steps: FallbackSpec[]): DerivedStep[] {
  return steps.map((s, i) => ({
    ...s,
    id: `__fallback_${(i + 1).toString()}`,
    order: i + 1,
    executable: false,
  }));
}

const LOGIN_STEPS: FallbackSpec[] = [
  {
    title: "Navigate to login page",
    type: "navigation",
    instruction: "Open the login page.",
    expected: "Login form is visible.",
  },
  {
    title: "Fill credentials",
    type: "action",
    instruction: "Enter a valid email and password into the login form.",
    expected: "Credentials are entered into the fields.",
  },
  {
    title: "Submit login form",
    type: "action",
    instruction: "Click the Sign In button.",
    expected: "The application processes the login attempt.",
  },
];

/**
 * Best-effort steps derived from a case's title/slug when the server has none.
 * Intentionally coarse — the UI labels these as generated fallbacks so QA knows
 * they are not the authoritative MCP/generated steps.
 *
 * TODO(evidence): replace with real steps sourced from the MCP plan / generated
 * test data (packages/lifecycle plan_frontend.py already carries typed steps —
 * ensure they survive the publish → bulk-import round-trip so this fallback is
 * never needed for published cases).
 */
export function generateFallbackSteps(nameOrSlug: string): DerivedStep[] {
  const key = nameOrSlug.toLowerCase();

  if (/login|sign[\s_-]?in|auth/.test(key)) {
    const steps = [...LOGIN_STEPS];
    if (/dashboard/.test(key)) {
      steps.push({
        title: "Verify dashboard is visible",
        type: "assertion",
        instruction: "Check that the dashboard renders after a successful login.",
        expected: "Dashboard page is visible with its summary.",
      });
    } else if (/error|invalid|fail/.test(key)) {
      steps.push({
        title: "Verify error is shown",
        type: "assertion",
        instruction: "Check that an error message is shown and the user stays on login.",
        expected: "An error message is visible; URL remains on the login page.",
      });
    }
    return fallback(steps);
  }

  if (/dashboard/.test(key)) {
    return fallback([
      {
        title: "Log in",
        type: "action",
        instruction: "Sign in with a valid account.",
        expected: "User is authenticated.",
      },
      {
        title: "Open dashboard",
        type: "navigation",
        instruction: "Navigate to the dashboard.",
        expected: "Dashboard page loads.",
      },
      {
        title: "Verify dashboard summary",
        type: "assertion",
        instruction: "Check that the dashboard summary cards are rendered.",
        expected: "Dashboard summary is visible.",
      },
    ]);
  }

  if (/product|item|catalog/.test(key)) {
    const steps: FallbackSpec[] = [
      {
        title: "Log in",
        type: "action",
        instruction: "Sign in with a valid account.",
        expected: "User is authenticated.",
      },
      {
        title: "Open products page",
        type: "navigation",
        instruction: "Navigate to the products list.",
        expected: "Products page is visible.",
      },
    ];
    if (/create|add|new|form/.test(key)) {
      steps.push(
        {
          title: "Fill product form",
          type: "action",
          instruction: "Fill the required fields in the product form and submit.",
          expected: "The form is submitted.",
        },
        {
          title: "Verify return to list",
          type: "assertion",
          instruction: "Check that the app returns to the products list with the new product.",
          expected: "Products list is shown and includes the created product.",
        },
      );
    } else {
      steps.push({
        title: "Verify products loaded",
        type: "assertion",
        instruction: "Check that the products list is rendered.",
        expected: "Products list is visible.",
      });
    }
    return fallback(steps);
  }

  if (/search|filter|query/.test(key)) {
    return fallback([
      {
        title: "Open the page",
        type: "navigation",
        instruction: "Navigate to the page that has the search input.",
        expected: "The page and its search input are visible.",
      },
      {
        title: "Enter a search keyword",
        type: "action",
        instruction: "Type a keyword into the search input.",
        expected: "The keyword is entered.",
      },
      {
        title: "Verify results",
        type: "assertion",
        instruction: "Check that the results (or empty state) match the keyword.",
        expected: /no[\s_-]?match|empty/.test(key)
          ? "An empty state is shown."
          : "Matching results are shown.",
      },
    ]);
  }

  // Generic scenario.
  return fallback([
    {
      title: "Open the application",
      type: "navigation",
      instruction: "Open the application under test.",
      expected: "The application is reachable.",
    },
    {
      title: "Execute the scenario",
      type: "action",
      instruction: "Perform the actions this test case describes.",
      expected: "The scenario runs without error.",
    },
    {
      title: "Verify expected result",
      type: "assertion",
      instruction: "Check the expected outcome of the scenario.",
      expected: "The expected result is observed.",
    },
  ]);
}

// ---------------------------------------------------------------------------
// Duration formatting
// ---------------------------------------------------------------------------

/** Compact duration label for run/step timings: `850ms`, `4.2s`, `2m 5s`. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms.toString()}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m.toString()}m ${Math.round(s % 60).toString()}s`;
}

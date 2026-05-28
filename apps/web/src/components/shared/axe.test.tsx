import { Inbox } from "lucide-react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import type { AxeMatchers } from "vitest-axe";
import * as axeMatchers from "vitest-axe/matchers";

import { EmptyState } from "@/components/shared/EmptyState";
import { Gauge } from "@/components/shared/Gauge";
import { KpiCard } from "@/components/shared/KpiCard";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatusBadge } from "@/components/shared/StatusBadge";

// vitest-axe ships an `extend-expect` augmentation targeted at the legacy
// `Vi` global namespace, which doesn't reach `expect` in Vitest 2.x. Augment
// the Vitest module directly so `toHaveNoViolations` is typed here.
declare module "vitest" {
  interface Assertion<T> extends AxeMatchers {
    __axe?: T;
  }
  interface AsymmetricMatchersContaining extends AxeMatchers {
    __axe?: never;
  }
}

// Register the toHaveNoViolations matcher with Vitest's expect.
expect.extend(axeMatchers);

/**
 * Baseline a11y check (Task 11.3). We aggregate the most-rendered shared
 * primitives onto one host element and run axe against the whole tree. This
 * is intentionally narrower than a full page audit (Dashboard would pull in
 * MSW + router state) — the goal in M1b is to catch regressions in the
 * shared kit before page-level coverage lands in M4.
 */
describe("a11y baseline (shared primitives)", () => {
  it("has no WCAG 2.0 A/AA axe violations", async () => {
    const { container } = render(
      <div>
        <KpiCard label="Pass rate" value="92%" />
        <Gauge value={72} label="Score" />
        <ProgressBar value={50} label="Coverage" />
        <StatusBadge status="pass" label="Healthy" />
        <EmptyState icon={Inbox} title="Nothing here" subtitle="Add an item to start" />
      </div>,
    );
    const results = await axe(container, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
    });
    await expect(results).toHaveNoViolations();
  });
});

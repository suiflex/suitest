import "@testing-library/jest-dom/vitest";
// Initialize i18next once for the whole test run so route components that
// call `useTranslation()` resolve keys instead of emitting NO_I18NEXT_INSTANCE
// warnings (and missing-resource fallbacks).
import "../i18n";

import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "../mocks/server";

// jsdom doesn't implement scroll APIs; TanStack Router calls them on every
// navigation, which spams the test output with "Not implemented" warnings.
// Provide silent no-op shims.
if (globalThis.window !== undefined) {
  globalThis.scrollTo = vi.fn();
  globalThis.scroll = vi.fn();
}

// jsdom doesn't ship a ResizeObserver implementation, but Radix UI primitives
// (used by shadcn) call into it from Popover/Dialog. Provide a no-op stub so
// shell tests can mount Tooltip/CommandDialog without explosions.
class ResizeObserverStub {
  observe(): void {
    // no-op
  }
  unobserve(): void {
    // no-op
  }
  disconnect(): void {
    // no-op
  }
}
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom also lacks PointerEvent setup used by Radix Dialog focus traps.
if (typeof globalThis.HTMLElement !== "undefined") {
  const proto = globalThis.HTMLElement.prototype as unknown as Record<string, unknown>;
  if (!("hasPointerCapture" in proto)) {
    proto["hasPointerCapture"] = () => false;
  }
  if (!("releasePointerCapture" in proto)) {
    proto["releasePointerCapture"] = () => undefined;
  }
  if (!("scrollIntoView" in proto)) {
    proto["scrollIntoView"] = () => undefined;
  }
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

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

// jsdom has no ImageData constructor, but the screenshot-diff math (M12-1)
// constructs `new ImageData(...)`. Provide a minimal polyfill covering both
// real overloads — `new ImageData(width, height)` allocates a zeroed array,
// `new ImageData(data, width, height?)` wraps an existing one — enough for the
// pure diff functions to run and for tests to assert on dimensions without a
// real canvas.
if (typeof globalThis.ImageData === "undefined") {
  class ImageDataPolyfill {
    readonly width: number;
    readonly height: number;
    readonly data: Uint8ClampedArray;
    constructor(sw: number | Uint8ClampedArray, sh?: number) {
      if (typeof sw === "number") {
        const w = sw;
        const h = sh ?? 0;
        this.width = w;
        this.height = h;
        this.data = new Uint8ClampedArray(w * h * 4);
      } else {
        this.data = sw;
        this.width = sh ?? 0;
        this.height = Math.floor(this.data.length / Math.max(this.width * 4, 1));
      }
    }
  }
  globalThis.ImageData = ImageDataPolyfill as unknown as typeof ImageData;
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

// jsdom's HTMLCanvasElement.getContext is a stub that logs "Not implemented"
// on every call. The screenshot-diff viewer (M12-1) calls getContext in an
// effect; it guards a `null` return, but jsdom still prints the warning (its
// stub *is* a function, so a `typeof !== "function"` guard would never install).
// Override unconditionally so the canvas path is exercised silently — the pure
// diff math (tested separately) stays the source of truth.
if (typeof globalThis.HTMLCanvasElement !== "undefined") {
  const proto = globalThis.HTMLCanvasElement.prototype as unknown as Record<
    string,
    unknown
  >;
  proto.getContext = () => null;
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

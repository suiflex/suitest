import "@testing-library/jest-dom/vitest";

import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "../mocks/server";

// jsdom doesn't implement scroll APIs; TanStack Router calls them on every
// navigation, which spams the test output with "Not implemented" warnings.
// Provide silent no-op shims.
if (globalThis.window !== undefined) {
  globalThis.scrollTo = vi.fn();
  globalThis.scroll = vi.fn();
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

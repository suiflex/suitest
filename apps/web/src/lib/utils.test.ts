import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("joins truthy classes", () => {
    expect(cn("a", false && "b", "c")).toBe("a c");
  });

  it("dedupes via tailwind-merge", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });
});

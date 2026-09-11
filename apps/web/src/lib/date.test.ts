import { describe, expect, it } from "vitest";

import { formatRelativeTime, formatTimestamp, parseUtcDate } from "@/lib/date";

describe("parseUtcDate", () => {
  it("parses ISO string with explicit Z", () => {
    const d = parseUtcDate("2026-09-10T10:00:00Z");
    expect(d).not.toBeNull();
    expect(d?.toISOString()).toBe("2026-09-10T10:00:00.000Z");
  });

  it("normalizes naive ISO string without Z into UTC (resolving Issue #176)", () => {
    const d = parseUtcDate("2026-09-10T10:00:00");
    expect(d).not.toBeNull();
    // Must be interpreted as 10:00:00 UTC, NOT local time!
    expect(d?.toISOString()).toBe("2026-09-10T10:00:00.000Z");
  });

  it("normalizes naive string with space instead of T into UTC", () => {
    const d = parseUtcDate("2026-09-10 10:00:00");
    expect(d).not.toBeNull();
    expect(d?.toISOString()).toBe("2026-09-10T10:00:00.000Z");
  });

  it("respects explicit timezone offset", () => {
    const d = parseUtcDate("2026-09-10T10:00:00+07:00");
    expect(d).not.toBeNull();
    expect(d?.toISOString()).toBe("2026-09-10T03:00:00.000Z");
  });

  it("handles Date objects directly", () => {
    const input = new Date("2026-09-10T10:00:00Z");
    const d = parseUtcDate(input);
    expect(d).toBe(input);
  });

  it("returns null for null, undefined, empty, or invalid dates", () => {
    expect(parseUtcDate(null)).toBeNull();
    expect(parseUtcDate(undefined)).toBeNull();
    expect(parseUtcDate("")).toBeNull();
    expect(parseUtcDate("   ")).toBeNull();
    expect(parseUtcDate("invalid-date-string")).toBeNull();
  });
});

describe("formatTimestamp", () => {
  it("formats valid UTC timestamp to localized string", () => {
    const str = formatTimestamp("2026-09-10T10:00:00Z");
    expect(str).not.toBe("—");
    expect(typeof str).toBe("string");
  });

  it("returns fallback for null or empty string", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
    expect(formatTimestamp("", "N/A")).toBe("N/A");
  });

  it("returns fallback for invalid date string or unparseable input", () => {
    expect(formatTimestamp("invalid-date")).toBe("—");
    expect(formatTimestamp("invalid-date", "N/A")).toBe("N/A");
    expect(formatTimestamp("not a date")).toBe("—");
  });
});

describe("formatRelativeTime", () => {
  it("calculates relative distance from normalized UTC timestamp", () => {
    // Current time or recent time
    const nowIso = new Date().toISOString();
    const relative = formatRelativeTime(nowIso);
    expect(relative).toMatch(/ago|in/);
  });

  it("returns fallback for null or undefined", () => {
    expect(formatRelativeTime(null)).toBe("—");
    expect(formatRelativeTime(undefined, { fallback: "Never" })).toBe("Never");
  });
});

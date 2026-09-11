import { formatDistanceToNow } from "date-fns";

/**
 * Safely parses an ISO date-time string, Date object, or timestamp into a JavaScript Date.
 *
 * ECMA-262 specifies that ISO-8601 strings without a timezone offset (e.g. "2026-09-10T10:00:00")
 * are parsed as local time by the browser. When the backend emits UTC timestamps without an explicit
 * "Z" designator, browsers in non-UTC timezones (e.g. UTC+7) misinterpret the time as local,
 * causing relative time calculations like formatDistanceToNow to be offset (Issue #176).
 *
 * parseUtcDate ensures that naive datetime strings are always treated as UTC.
 */
export function parseUtcDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value;
  }

  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  // Check if string contains a time component (T or space with HH:mm)
  const hasTime = trimmed.includes("T") || /\s\d{1,2}:\d{2}/.test(trimmed);
  // Check if string already ends with a timezone designator (Z or +HH:MM / -HH:MM offset)
  const hasOffset = /([zZ]|[+-]\d{2}(:?\d{2})?)$/.test(trimmed);

  let normalized = trimmed;
  if (hasTime && !hasOffset) {
    normalized = trimmed.replace(" ", "T") + "Z";
  }

  const parsed = new Date(normalized);
  return isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Formats a timestamp into a user-friendly localized string using the user's locale and timezone.
 * Returns fallback (default "—") if value is null, undefined, or unparseable.
 */
export function formatTimestamp(
  value: string | Date | null | undefined,
  fallback = "—",
): string {
  const d = parseUtcDate(value);
  if (!d) {
    return fallback;
  }
  return d.toLocaleString();
}

/**
 * Returns a human-readable relative time string (e.g. "less than a minute ago", "5 minutes ago").
 * Correctly handles naive UTC timestamps by normalizing with parseUtcDate.
 */
export function formatRelativeTime(
  value: string | Date | null | undefined,
  options: { addSuffix?: boolean; fallback?: string } = { addSuffix: true },
): string {
  const d = parseUtcDate(value);
  if (!d) {
    return options.fallback ?? "—";
  }
  return formatDistanceToNow(d, {
    addSuffix: options.addSuffix ?? true,
  });
}

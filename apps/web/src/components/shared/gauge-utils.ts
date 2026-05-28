/**
 * Color-threshold helper for {@link Gauge} / {@link SmallGauge} (UI_SPEC § 4.6).
 *
 * Lives in its own module so it can be unit-tested alongside the components
 * without tripping the `react-refresh/only-export-components` rule that
 * disallows non-component named exports in component files.
 */
export function gaugeColorClass(value: number): string {
  const v = clamp(value);
  if (v >= 80) return "text-accent";
  if (v >= 60) return "text-amber";
  return "text-red";
}

export function clampGaugeValue(value: number): number {
  return clamp(value);
}

function clamp(value: number): number {
  if (Number.isNaN(value)) return 0;
  if (value < 0) return 0;
  if (value > 100) return 100;
  return value;
}

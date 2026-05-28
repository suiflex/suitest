/**
 * Number formatters shared by {@link CostChip} and any future consumer that
 * needs to display LLM token/cost usage. Lives outside `CostChip.tsx` so the
 * component file stays components-only (react-refresh rule).
 */

/**
 * Format a token count using a single decimal "k"/"M" suffix above 1k.
 * `formatTokens(1000)` → `"1.0k"`, `formatTokens(4234)` → `"4.2k"`.
 */
export function formatTokens(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens < 0) return "0";
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)}M`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return tokens.toString();
}

/**
 * Format a numeric cost as a currency string. Defaults to USD with two
 * decimals for $1+ amounts, three decimals between 1¢ and $1, four decimals
 * for sub-cent amounts (useful for per-call cost preview).
 */
export function formatCost(cost: number, currency = "USD"): string {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  if (!Number.isFinite(cost) || cost < 0) return `${symbol}0.00`;
  if (cost < 0.01) return `${symbol}${cost.toFixed(4)}`;
  if (cost < 1) return `${symbol}${cost.toFixed(3)}`;
  return `${symbol}${cost.toFixed(2)}`;
}

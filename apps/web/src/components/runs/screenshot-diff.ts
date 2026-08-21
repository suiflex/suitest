/**
 * Pure screenshot-diff math — framework-free so it can be unit-tested without
 * rendering canvas (jsdom has no `getImageData`).
 *
 * M12-1 (ZERO tier, deterministic). Two images are compared at the **smaller
 * shared dimensions**: the larger image is compared only within the overlap,
 * which matches the practical "same viewport, different render" case and
 * avoids rejecting a diff just because one screenshot captured a scrollbar.
 *
 * `pixelDiffPct` returns the fraction of *compared* pixels whose RGBA distance
 * exceeds the threshold, as a percentage (0–100). `diffImage` produces an
 * overlay where changed pixels are bright red and unchanged pixels are dimmed
 * to a faint gray — the visualization the `ScreenshotDiffViewer` canvas renders.
 */

/** RGBA channels per pixel. */
const CHANNELS = 4;

/** Maximum possible per-channel distance (0–255). */
const MAX_CHANNEL = 255;

/**
 * Read a channel as a number. `Uint8ClampedArray` indexing returns
 * `number | undefined` under `noUncheckedIndexedAccess`; this local helper
 * restores the non-undefined read the arithmetic below relies on. The indices
 * are always in-bounds (they are computed from the overlap dimensions).
 */
function ch(data: Uint8ClampedArray, i: number): number {
  return data[i] as number;
}

/** Squared RGBA distance threshold above which a pixel is considered "changed". */
export const DEFAULT_PIXEL_THRESHOLD = 30;

/** Perceptual mode is scaffolded but not implemented in M12-1 (no LLM/dep). */
export type DiffMode = "pixel" | "perceptual";

export interface DiffOptions {
  /** RGB distance (0–255) above which a pixel is "changed"; compared as
   * distance² > threshold². Default 30 — a per-channel shift of ~30 reads as a
   * visible change while suppressing sub-threshold rendering noise. */
  threshold?: number;
}

/**
 * Fraction of compared pixels that differ, as a percentage 0–100.
 *
 * Both `ImageData` are compared over the intersection (min width × min height).
 * Returns `0` when either side has zero comparable pixels.
 */
export function pixelDiffPct(
  a: ImageData,
  b: ImageData,
  { threshold = DEFAULT_PIXEL_THRESHOLD }: DiffOptions = {},
): number {
  const w = Math.min(a.width, b.width);
  const h = Math.min(a.height, b.height);
  const comparable = w * h;
  if (comparable === 0) return 0;

  let changed = 0;
  const tSq = threshold * threshold;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * CHANNELS;
      const dr = ch(a.data, i) - ch(b.data, i);
      const dg = ch(a.data, i + 1) - ch(b.data, i + 1);
      const db = ch(a.data, i + 2) - ch(b.data, i + 2);
      // Ignore alpha: a transparent-vs-opaque pixel would dominate the diff
      // and mask real visual change. Compare RGB only.
      const distSq = dr * dr + dg * dg + db * db;
      if (distSq > tSq) changed++;
    }
  }
  return (changed / comparable) * 100;
}

/**
 * Build a visualization `ImageData` the size of the overlap. Changed pixels are
 * solid red (`#ff0000`); unchanged pixels are dimmed to a faint gray so the eye
 * lands on the changes. Returns a fresh `ImageData` — never mutates inputs.
 */
export function diffImage(
  a: ImageData,
  b: ImageData,
  { threshold = DEFAULT_PIXEL_THRESHOLD }: DiffOptions = {},
): ImageData {
  const w = Math.min(a.width, b.width);
  const h = Math.min(a.height, b.height);
  const out = new ImageData(w, h);
  const tSq = threshold * threshold;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * CHANNELS;
      const dr = ch(a.data, i) - ch(b.data, i);
      const dg = ch(a.data, i + 1) - ch(b.data, i + 1);
      const db = ch(a.data, i + 2) - ch(b.data, i + 2);
      const distSq = dr * dr + dg * dg + db * db;
      const changed = distSq > tSq;
      // Dim unchanged pixels to a low gray; flag changed as opaque red.
      const set = (idx: number, v: number): void => {
        out.data[idx] = v;
      };
      set(i, changed ? MAX_CHANNEL : 40);
      set(i + 1, changed ? 0 : 40);
      set(i + 2, changed ? 0 : 40);
      set(i + 3, MAX_CHANNEL);
    }
  }
  return out;
}

/** Color token for a diff percentage, matching the existing StateDiff pattern. */
export function diffPctColor(pct: number): "text-accent" | "text-amber" | "text-red" {
  if (pct < 1) return "text-accent";
  if (pct <= 10) return "text-amber";
  return "text-red";
}

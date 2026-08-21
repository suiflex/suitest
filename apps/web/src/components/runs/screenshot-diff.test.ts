import { describe, expect, it } from "vitest";

import {
  DEFAULT_PIXEL_THRESHOLD,
  diffImage,
  diffPctColor,
  pixelDiffPct,
} from "@/components/runs/screenshot-diff";

/** Build an ImageData filled with a single RGBA color. */
function solidImageData(
  width: number,
  height: number,
  r: number,
  g: number,
  b: number,
  a = 255,
): ImageData {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = r;
    data[i * 4 + 1] = g;
    data[i * 4 + 2] = b;
    data[i * 4 + 3] = a;
  }
  return new ImageData(data, width, height);
}

describe("pixelDiffPct", () => {
  it("returns 0 for identical images", () => {
    const a = solidImageData(4, 4, 10, 20, 30);
    const b = solidImageData(4, 4, 10, 20, 30);
    expect(pixelDiffPct(a, b)).toBe(0);
  });

  it("returns 100 when every pixel differs beyond threshold", () => {
    const a = solidImageData(4, 4, 0, 0, 0);
    const b = solidImageData(4, 4, 255, 255, 255);
    expect(pixelDiffPct(a, b)).toBe(100);
  });

  it("counts only pixels beyond the threshold", () => {
    // 2x2 = 4 px. One pixel shifted by 200 (changed), the rest identical.
    const a = solidImageData(2, 2, 0, 0, 0);
    const b = solidImageData(2, 2, 0, 0, 0);
    b.data[0] = 200; // r of pixel 0
    expect(pixelDiffPct(a, b)).toBe(25); // 1 of 4
  });

  it("ignores sub-threshold changes (RGB noise within tolerance)", () => {
    const a = solidImageData(2, 2, 100, 100, 100);
    const b = solidImageData(2, 2, 100, 100, 100);
    // shift one pixel by 5 in each channel — well below default threshold 30
    b.data[0] = 105;
    b.data[1] = 105;
    b.data[2] = 105;
    expect(pixelDiffPct(a, b)).toBe(0);
  }),

  it("respects a custom threshold", () => {
    const a = solidImageData(1, 1, 0, 0, 0);
    const b = solidImageData(1, 1, 10, 0, 0);
    // distance² = 100; default threshold² = 900 → not changed.
    expect(pixelDiffPct(a, b)).toBe(0);
    // threshold 5 → threshold² 25 < 100 → changed.
    expect(pixelDiffPct(a, b, { threshold: 5 })).toBe(100);
  });

  it("compares only the overlap when sizes differ", () => {
    const a = solidImageData(4, 4, 0, 0, 0);
    const b = solidImageData(2, 2, 255, 255, 255);
    // overlap 2x2 = 4 px, all changed → 100%, not 25% (4 of 16).
    expect(pixelDiffPct(a, b)).toBe(100);
  });

  it("returns 0 when there is no comparable overlap", () => {
    const a = solidImageData(0, 0, 0, 0, 0);
    const b = solidImageData(2, 2, 255, 255, 255);
    expect(pixelDiffPct(a, b)).toBe(0);
  });

  it("ignores alpha differences", () => {
    const a = solidImageData(2, 2, 50, 50, 50, 255);
    const b = solidImageData(2, 2, 50, 50, 50, 0);
    expect(pixelDiffPct(a, b)).toBe(0);
  });
});

describe("diffImage", () => {
  it("produces an ImageData sized to the overlap", () => {
    const a = solidImageData(4, 3, 0, 0, 0);
    const b = solidImageData(2, 5, 255, 255, 255);
    const out = diffImage(a, b);
    expect(out.width).toBe(2);
    expect(out.height).toBe(3);
  });

  it("flags changed pixels as opaque red", () => {
    const a = solidImageData(1, 1, 0, 0, 0);
    const b = solidImageData(1, 1, 255, 255, 255);
    const out = diffImage(a, b);
    expect(out.data[0]).toBe(255); // r
    expect(out.data[1]).toBe(0); // g
    expect(out.data[2]).toBe(0); // b
    expect(out.data[3]).toBe(255); // a
  });

  it("dims unchanged pixels to faint gray", () => {
    const a = solidImageData(1, 1, 10, 20, 30);
    const b = solidImageData(1, 1, 10, 20, 30);
    const out = diffImage(a, b);
    expect(out.data[0]).toBe(40);
    expect(out.data[3]).toBe(255);
  });

  it("does not mutate the input ImageData", () => {
    const a = solidImageData(1, 1, 10, 20, 30);
    const b = solidImageData(1, 1, 200, 200, 200);
    const aBefore = a.data[0];
    const bBefore = b.data[0];
    diffImage(a, b);
    expect(a.data[0]).toBe(aBefore);
    expect(b.data[0]).toBe(bBefore);
  });
});

describe("diffPctColor", () => {
  it("uses accent under 1%", () => {
    expect(diffPctColor(0)).toBe("text-accent");
    expect(diffPctColor(0.9)).toBe("text-accent");
  });

  it("uses amber between 1 and 10", () => {
    expect(diffPctColor(1)).toBe("text-amber");
    expect(diffPctColor(10)).toBe("text-amber");
  });

  it("uses red above 10", () => {
    expect(diffPctColor(10.01)).toBe("text-red");
    expect(diffPctColor(100)).toBe("text-red");
  });
});

describe("DEFAULT_PIXEL_THRESHOLD", () => {
  it("matches the documented default", () => {
    expect(DEFAULT_PIXEL_THRESHOLD).toBe(30);
  });
});

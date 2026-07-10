import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { applyTheme, getTheme, setTheme } from "@/lib/theme";

const STORAGE_KEY = "suitest.theme";

describe("theme", () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.classList.remove("dark", "light");
  });

  afterEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.classList.remove("dark", "light");
  });

  it("defaults to dark when nothing is stored", () => {
    expect(getTheme()).toBe("dark");
  });

  it("reads a stored theme", () => {
    localStorage.setItem(STORAGE_KEY, "light");
    expect(getTheme()).toBe("light");
  });

  it("ignores a garbage stored value", () => {
    localStorage.setItem(STORAGE_KEY, "neon");
    expect(getTheme()).toBe("dark");
  });

  it("setTheme persists and swaps the html class", () => {
    setTheme("light");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    setTheme("dark");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("applyTheme swaps class without touching storage", () => {
    applyTheme("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

/**
 * Dark / light theme, persisted in localStorage — mirrors the plain-storage
 * pattern of `src/i18n.ts` (no zustand). The theme is applied by toggling a
 * `dark` / `light` class on `<html>`; the design tokens in `globals.css`
 * re-point under `html.light`, so switching the class re-themes the whole app.
 *
 * An inline script in `index.html` reads the same key pre-paint (no flash);
 * this module keeps it in sync on user toggles.
 */
export type Theme = "dark" | "light";

const STORAGE_KEY = "suitest.theme";

// Bare `localStorage` with a typeof guard — the same persistence pattern as
// src/i18n.ts (proven under the jsdom test env).
export function getTheme(): Theme {
  if (typeof localStorage !== "undefined") {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  }
  return "dark";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);
}

/** Switch the active theme and persist it so the choice survives reloads. */
export function setTheme(theme: Theme): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(STORAGE_KEY, theme);
  }
  applyTheme(theme);
}

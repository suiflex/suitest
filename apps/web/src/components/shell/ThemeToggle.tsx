import { Moon, Sun } from "lucide-react";
import { useState } from "react";

import { getTheme, setTheme, type Theme } from "@/lib/theme";

/**
 * Topbar dark/light toggle. Flips the persisted theme (localStorage via
 * `@/lib/theme`) which re-points the design tokens under `html.light` /
 * `html.dark`. Seeded from `getTheme()` so it reflects the value the inline
 * boot script already applied.
 */
export function ThemeToggle(): React.ReactElement {
  const [theme, setThemeState] = useState<Theme>(() => getTheme());
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next);
        setThemeState(next);
      }}
      aria-label={`Switch to ${next} theme`}
      className="flex h-7 w-7 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
      data-testid="theme-toggle"
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

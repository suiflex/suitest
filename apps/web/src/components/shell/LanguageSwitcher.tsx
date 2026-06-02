import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

import { setLocale, type Locale } from "@/i18n";

const LOCALES: { value: Locale; label: string }[] = [
  { value: "en", label: "EN" },
  { value: "id", label: "ID" },
];

/**
 * Topbar language switcher (M4-12). Toggles between English and Bahasa Indonesia
 * and persists the choice via {@link setLocale} (localStorage), so the selection
 * survives reloads. Re-renders all `useTranslation` consumers on change.
 */
export function LanguageSwitcher(): React.ReactElement {
  const { i18n } = useTranslation();
  const current = (i18n.language.startsWith("id") ? "id" : "en") as Locale;

  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-bg-elev-1 p-0.5"
      role="group"
      aria-label="Language"
      data-testid="language-switcher"
    >
      <Languages className="ml-1 mr-0.5 h-3.5 w-3.5 text-fg-4" aria-hidden="true" />
      {LOCALES.map((loc) => (
        <button
          key={loc.value}
          type="button"
          onClick={() => void setLocale(loc.value)}
          aria-pressed={current === loc.value}
          className={
            current === loc.value
              ? "rounded px-1.5 py-0.5 text-[11px] font-medium bg-bg-elev-2 text-fg-1"
              : "rounded px-1.5 py-0.5 text-[11px] text-fg-4 hover:text-fg-1"
          }
        >
          {loc.label}
        </button>
      ))}
    </div>
  );
}

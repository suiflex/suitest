import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import id from "./locales/id.json";

/**
 * i18n scaffolding (Task 12). M1b ships title-only translation across the 9
 * read-only screens so plumbing is exercised end-to-end. Full copy
 * extraction lands in M4 alongside the locale-switcher in the topbar.
 *
 * Resources are bundled as flat JSON dictionaries keyed by `<screen>.title`
 * (not nested namespaces) so additions can be appended without touching
 * code. Bahasa Indonesia values follow CLAUDE.md § 3.4 (product UI in
 * English, BI allowed for greetings + empty states — we use BI for screen
 * titles here as the canonical translation target).
 */
void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    id: { translation: id },
  },
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;

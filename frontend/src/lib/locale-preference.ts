import type { Locale } from "@/lib/i18n";

const LOCALE_KEY = "on1y_locale";

export function loadStoredLocale(): Locale {
  if (typeof window === "undefined") {
    return "zh";
  }
  const value = localStorage.getItem(LOCALE_KEY);
  return value === "en" ? "en" : "zh";
}

export function persistStoredLocale(locale: Locale): void {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.setItem(LOCALE_KEY, locale);
}

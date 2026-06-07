export type AppearanceMode = "light" | "dark" | "system";

const STORAGE_KEY = "on1y_appearance";

export function loadStoredAppearance(): AppearanceMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return "system";
}

export function persistStoredAppearance(mode: AppearanceMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveDark(mode: AppearanceMode): boolean {
  if (mode === "dark") {
    return true;
  }
  if (mode === "light") {
    return false;
  }
  return systemPrefersDark();
}

export function applyAppearance(mode: AppearanceMode): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  const dark = resolveDark(mode);
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

export function watchSystemAppearance(onChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const handler = (): void => onChange();
  media.addEventListener("change", handler);
  return () => media.removeEventListener("change", handler);
}

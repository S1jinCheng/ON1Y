export type SettingsTabKey = "general" | "account" | "subscriptions" | "ai" | "push" | "about";

export const OPEN_SETTINGS_EVENT = "on1y-open-settings";
export const SETTINGS_CLOSED_EVENT = "on1y-settings-closed";
export const REQUEST_INITIAL_SYNC_EVENT = "on1y-request-initial-sync";
export const SHOW_FIRST_RUN_GUIDE_EVENT = "on1y-show-first-run-guide";

const TAB_STORAGE_KEY = "on1y-settings-tab";

export function openSettingsTab(tab: SettingsTabKey | "platforms" | "cookies"): void {
  const resolved = tab === "platforms" || tab === "cookies" ? "subscriptions" : tab;
  try {
    sessionStorage.setItem(TAB_STORAGE_KEY, resolved);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(OPEN_SETTINGS_EVENT));
}

export function consumeRequestedSettingsTab(): SettingsTabKey | null {
  try {
    const raw = sessionStorage.getItem(TAB_STORAGE_KEY);
    sessionStorage.removeItem(TAB_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    if (raw === "platforms" || raw === "cookies") {
      return "subscriptions";
    }
    return raw as SettingsTabKey;
  } catch {
    return null;
  }
}

export function requestInitialSync(): void {
  window.dispatchEvent(new Event(REQUEST_INITIAL_SYNC_EVENT));
}

export function showFirstRunGuide(): void {
  window.dispatchEvent(new Event(SHOW_FIRST_RUN_GUIDE_EVENT));
}

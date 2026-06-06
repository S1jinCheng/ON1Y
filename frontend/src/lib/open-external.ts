import type { MouseEvent } from "react";

/** Open http(s) links in the system browser (Tauri desktop) or a new tab (web). */

type TauriGlobals = {
  opener?: { openUrl: (url: string) => Promise<void> };
  core?: { invoke: (cmd: string, args: Record<string, string>) => Promise<unknown> };
};

function tauriGlobals(): TauriGlobals | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return (window as Window & { __TAURI__?: TauriGlobals }).__TAURI__;
}

export function isExternalHttpUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("http://") || trimmed.startsWith("https://");
}

export async function openExternalUrl(url: string): Promise<void> {
  const trimmed = (url || "").trim();
  if (!trimmed || !isExternalHttpUrl(trimmed)) {
    return;
  }

  const tauri = tauriGlobals();
  if (tauri?.opener?.openUrl) {
    try {
      await tauri.opener.openUrl(trimmed);
      return;
    } catch {
      /* try invoke fallback */
    }
  }
  if (tauri?.core?.invoke) {
    try {
      await tauri.core.invoke("open_external_url", { url: trimmed });
      return;
    } catch {
      /* fall through */
    }
  }

  window.open(trimmed, "_blank", "noopener,noreferrer");
}

export function handleExternalLinkClick(
  event: MouseEvent<HTMLAnchorElement>,
  url: string | null | undefined
): void {
  const trimmed = (url || "").trim();
  if (!trimmed || !isExternalHttpUrl(trimmed)) {
    return;
  }
  if (!tauriGlobals()) {
    return;
  }
  event.preventDefault();
  void openExternalUrl(trimmed);
}

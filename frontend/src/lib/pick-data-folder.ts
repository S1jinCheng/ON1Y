import { pickFolderPath } from "@/lib/api";

type TauriGlobals = {
  core?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
};

function tauriGlobals(): TauriGlobals | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return (window as Window & { __TAURI__?: TauriGlobals }).__TAURI__;
}

export function isDesktopShell(): boolean {
  return Boolean(tauriGlobals()?.core?.invoke);
}

async function pickFolderTauri(): Promise<string | null> {
  const tauri = tauriGlobals();
  if (!tauri?.core?.invoke) {
    throw new Error("Desktop folder picker is unavailable");
  }
  const result = await tauri.core.invoke("pick_data_folder");
  if (typeof result === "string" && result.trim()) {
    return result.trim();
  }
  return null;
}

/** Native folder picker (Tauri desktop, or server dialog for web UI). */
export async function pickFolder(): Promise<string | null> {
  if (isDesktopShell()) {
    return pickFolderTauri();
  }
  try {
    const { path } = await pickFolderPath();
    return path?.trim() || null;
  } catch {
    return null;
  }
}

/** @deprecated use pickFolder */
export const pickDataFolder = pickFolder;

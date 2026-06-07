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

/** Native folder picker (desktop). Returns absolute path or null if cancelled. */
export async function pickDataFolder(): Promise<string | null> {
  const tauri = tauriGlobals();
  if (!tauri?.core?.invoke) {
    return null;
  }
  try {
    const result = await tauri.core.invoke("pick_data_folder");
    if (typeof result === "string" && result.trim()) {
      return result.trim();
    }
    return null;
  } catch {
    return null;
  }
}

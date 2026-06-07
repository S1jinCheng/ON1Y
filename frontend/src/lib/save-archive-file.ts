type TauriGlobals = {
  core?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
};

function tauriGlobals(): TauriGlobals | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return (window as Window & { __TAURI__?: TauriGlobals }).__TAURI__;
}

/** Native save dialog (desktop). Returns saved path or null if cancelled. */
export async function saveArchiveFile(defaultName: string, data: Uint8Array): Promise<string | null> {
  const tauri = tauriGlobals();
  if (!tauri?.core?.invoke) {
    return null;
  }
  try {
    const result = await tauri.core.invoke("save_archive_file", {
      defaultName,
      data: Array.from(data)
    });
    if (typeof result === "string" && result.trim()) {
      return result.trim();
    }
    return null;
  } catch {
    return null;
  }
}

/** Trigger a file download in the browser (must run in the same click handler, before await). */
export function triggerBrowserFileDownload(url: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

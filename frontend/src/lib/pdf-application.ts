type TauriGlobals = {
  core?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
};

function tauriGlobals(): TauriGlobals | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return (window as Window & { __TAURI__?: TauriGlobals }).__TAURI__;
}

/** Select a local PDF reader executable in the desktop shell. */
export async function pickPdfApplication(): Promise<string | null> {
  const tauri = tauriGlobals();
  if (!tauri?.core?.invoke) {
    throw new Error("Desktop application picker is unavailable");
  }
  const result = await tauri.core.invoke("pick_pdf_application");
  return typeof result === "string" && result.trim() ? result.trim() : null;
}

/** Open a PDF with the exact application selected by the user. */
export async function openPdfWithApplication(
  applicationPath: string,
  pdfPath: string
): Promise<void> {
  const tauri = tauriGlobals();
  if (!tauri?.core?.invoke) {
    throw new Error("Custom PDF applications are only available in the desktop app");
  }
  await tauri.core.invoke("open_pdf_with_application", { applicationPath, pdfPath });
}
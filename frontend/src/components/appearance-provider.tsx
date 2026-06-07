"use client";

import { useEffect, useState } from "react";

import {
  applyAppearance,
  loadStoredAppearance,
  persistStoredAppearance,
  type AppearanceMode,
  watchSystemAppearance
} from "@/lib/appearance";
import { getUserProfile } from "@/lib/api";

export function AppearanceProvider(): null {
  const [mode, setMode] = useState<AppearanceMode>(() => loadStoredAppearance());

  useEffect(() => {
    applyAppearance(mode);
  }, [mode]);

  useEffect(() => {
    if (mode !== "system") {
      return undefined;
    }
    return watchSystemAppearance(() => applyAppearance("system"));
  }, [mode]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const profile = await getUserProfile();
        if (cancelled) {
          return;
        }
        const fromProfile = profile.app?.appearance;
        const stored = loadStoredAppearance();
        const next =
          fromProfile === "light" || fromProfile === "dark" || fromProfile === "system"
            ? fromProfile
            : stored;
        persistStoredAppearance(next);
        setMode(next);
      } catch {
        /* not logged in yet */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onAppearance = (event: Event): void => {
      const detail = (event as CustomEvent<AppearanceMode>).detail;
      if (detail === "light" || detail === "dark" || detail === "system") {
        setMode(detail);
      }
    };
    window.addEventListener("on1y-appearance-change", onAppearance);
    return () => window.removeEventListener("on1y-appearance-change", onAppearance);
  }, []);

  return null;
}

export function notifyAppearanceChange(mode: AppearanceMode): void {
  window.dispatchEvent(new CustomEvent("on1y-appearance-change", { detail: mode }));
}

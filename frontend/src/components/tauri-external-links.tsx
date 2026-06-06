"use client";

import { useEffect } from "react";

import { isExternalHttpUrl, openExternalUrl } from "@/lib/open-external";

/** Capture external link clicks when running inside the Tauri desktop shell. */
export function TauriExternalLinks(): null {
  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI__" in window)) {
      return;
    }

    function onClick(event: MouseEvent): void {
      if (event.defaultPrevented) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) {
        return;
      }
      const href = anchor.getAttribute("href") || "";
      if (!isExternalHttpUrl(href)) {
        return;
      }
      if (
        href.startsWith("http://127.0.0.1") ||
        href.startsWith("http://localhost") ||
        href.includes("://tauri.localhost")
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      void openExternalUrl(href);
    }

    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  return null;
}

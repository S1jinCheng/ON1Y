"use client";

import { useCallback, useEffect, useState } from "react";

import { getAppUpdateStatus, type AppUpdateStatus } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { openExternalUrl } from "@/lib/open-external";

const POLL_MS = 24 * 60 * 60 * 1000;
const DISMISS_KEY = "on1y-update-dismissed";

function dismissedVersion(version: string | null | undefined): boolean {
  if (!version || typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(DISMISS_KEY) === version;
}

function persistDismiss(version: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(DISMISS_KEY, version);
}

export function AppUpdateBanner(props: { locale: Locale }): JSX.Element | null {
  const { locale } = props;
  const zh = locale === "zh";
  const [update, setUpdate] = useState<AppUpdateStatus | null>(null);
  const [hidden, setHidden] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const status = await getAppUpdateStatus(false);
      setUpdate(status);
      if (status.has_update && status.latest_version && dismissedVersion(status.latest_version)) {
        setHidden(true);
      } else {
        setHidden(false);
      }
    } catch {
      /* backend offline */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void refresh();
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (!update?.check_enabled || !update.has_update || hidden || !update.latest_version) {
    return null;
  }

  const downloadUrl = update.download_url || update.release_url || "";

  return (
    <div
      className="flex shrink-0 items-center justify-between gap-4 border-b border-sky-500/30 bg-sky-500/10 px-4 py-2 text-sm text-sky-950 dark:text-sky-100"
      role="status"
    >
      <p className="min-w-0 truncate">
        {zh
          ? `新版本 v${update.latest_version} 可用（当前 v${update.current_version}）`
          : `Update v${update.latest_version} available (current v${update.current_version})`}
      </p>
      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          className="text-xs font-medium underline-offset-2 hover:underline"
          onClick={() => {
            if (downloadUrl) {
              void openExternalUrl(downloadUrl);
            }
          }}
        >
          {zh ? "下载更新" : "Download"}
        </button>
        <button
          type="button"
          className="text-xs font-medium underline-offset-2 hover:underline"
          onClick={() => {
            persistDismiss(update.latest_version!);
            setHidden(true);
          }}
        >
          {zh ? "稍后" : "Later"}
        </button>
      </div>
    </div>
  );
}

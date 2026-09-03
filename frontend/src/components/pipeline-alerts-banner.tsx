"use client";

import { useCallback, useEffect, useState } from "react";

import { acknowledgePipelineAlerts, getPipelineAlerts, type PipelineAlert } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { platformLabel } from "@/lib/platform-label";

const POLL_MS = 30_000;

const BURGUNDY_BAR =
  "border-[#722F37]/35 bg-[#722F37]/10 text-[#5a1f28] dark:border-[#a34d5c]/40 dark:bg-[#3d151c] dark:text-[#f2d6da]";

function alertSummary(alert: PipelineAlert, locale: Locale): string {
  const platform = platformLabel(alert.platform, locale);
  if (alert.kind === "cookie_expired") {
    return locale === "zh"
      ? `${platform} 登录已失效，请到设置更新 Cookie`
      : `${platform} sign-in expired — update cookies in Settings`;
  }
  if (alert.kind === "antibot") {
    return locale === "zh"
      ? `${platform} 暂时无法访问，请稍后再试`
      : `${platform} is temporarily unavailable — try again later`;
  }
  if (alert.kind === "rate_limit") {
    return locale === "zh"
      ? `${platform} 字幕接口被限流，请稍后再试`
      : `${platform} subtitle requests are rate-limited — try again later`;
  }
  return locale === "zh"
    ? `${platform} 同步遇到问题，请稍后再试`
    : `${platform} sync issue — try again later`;
}

export function PipelineAlertsBanner(props: { locale: Locale }): JSX.Element | null {
  const { locale } = props;
  const [alerts, setAlerts] = useState<PipelineAlert[]>([]);
  const [dismissing, setDismissing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const rows = await getPipelineAlerts(true);
      setAlerts(rows);
    } catch {
      /* ignore when backend offline */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void refresh();
      }
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void refresh();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  async function dismiss(): Promise<void> {
    setDismissing(true);
    try {
      await acknowledgePipelineAlerts(true);
      setAlerts([]);
    } finally {
      setDismissing(false);
    }
  }

  if (alerts.length === 0) {
    return null;
  }

  const primary = alerts[alerts.length - 1];

  return (
    <div
      className={`flex shrink-0 items-center justify-between gap-4 border-b px-4 py-2 text-sm ${BURGUNDY_BAR}`}
      role="alert"
    >
      <p className="min-w-0 truncate">{alertSummary(primary, locale)}</p>
      <button
        type="button"
        className="shrink-0 text-xs font-medium underline-offset-2 hover:underline disabled:opacity-50"
        disabled={dismissing}
        onClick={() => void dismiss()}
      >
        {dismissing ? (locale === "zh" ? "…" : "…") : locale === "zh" ? "知道了" : "OK"}
      </button>
    </div>
  );
}

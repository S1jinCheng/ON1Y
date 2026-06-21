"use client";

import type { CSSProperties } from "react";

import type { BookAcquireResult } from "@/lib/book-types";
import {
  kindleDeliveryTooltip,
  parseKindleDetailFromNotes,
  resolveKindleDeliveryLight
} from "@/lib/kindle-delivery";
import type { Locale } from "@/lib/types";

export type BookAcquireNotice = {
  message: string;
  kind: "success" | "warn" | "error";
};

export type KindleSendFeedback = {
  kindle_sent: boolean;
  kindle_status?: "sent" | "skipped" | "failed";
  kindle_detail?: string | null;
};

const BAR_STYLES: Record<BookAcquireNotice["kind"], string> = {
  success:
    "border-emerald-700/35 bg-emerald-700/10 text-emerald-950 dark:border-emerald-500/40 dark:bg-emerald-950/40 dark:text-emerald-100",
  warn: "border-amber-600/35 bg-amber-600/10 text-amber-950 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-100",
  error:
    "border-[#722F37]/35 bg-[#722F37]/10 text-[#5a1f28] dark:border-[#a34d5c]/40 dark:bg-[#3d151c] dark:text-[#f2d6da]"
};

function formatFileSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Kindle push result: SMTP send OK → success; otherwise warn with reason (user can retry). */
export function buildKindleSendNotice(locale: Locale, result: KindleSendFeedback): BookAcquireNotice {
  const detail = result.kindle_detail?.trim();
  if (result.kindle_status === "sent" || result.kindle_sent) {
    return {
      kind: "success",
      message:
        locale === "zh"
          ? "已通过邮箱发送到 Kindle（邮件服务器已接受）。若设备暂未显示，请稍等或检查亚马逊已批准发件邮箱；也可在书架重新发送。"
          : "Emailed to Kindle (SMTP accepted). If it has not appeared yet, wait or check your approved sender in Amazon; you can resend from the shelf.",
    };
  }
  if (result.kindle_status === "failed") {
    return {
      kind: "warn",
      message:
        locale === "zh"
          ? `Kindle 邮件发送失败${detail ? `：${detail}` : ""}。电子书仍在本地，可在书架点击「发送到 Kindle」重试。`
          : `Kindle email failed${detail ? `: ${detail}` : ""}. The file is saved locally — use Send to Kindle on the shelf to retry.`,
    };
  }
  return {
    kind: "warn",
    message:
      locale === "zh"
        ? detail
          ? `未发送到 Kindle：${detail}`
          : "未发送到 Kindle（未配置收件邮箱或已跳过）。可在设置中配置后，于书架手动发送。"
        : detail
          ? `Kindle not sent: ${detail}`
          : "Kindle not sent (no address configured or skipped). Configure in Settings, then send from the shelf.",
  };
}

export type KindleLightState = "none" | "local" | "kindle";

const NEON_DOTS: Record<KindleLightState, { core: string; glow: string }> = {
  none: { core: "#FF0000", glow: "#FF0000" },
  local: { core: "#FCEE09", glow: "#FFF000" },
  kindle: { core: "#00FF22", glow: "#00FF44" }
};

function KindleNeonDot(props: { state: KindleLightState; active: boolean }): JSX.Element {
  const { state, active } = props;
  const { core, glow } = NEON_DOTS[state];
  return (
    <span
      className={`kindle-neon-dot ${active ? "kindle-neon-dot--on" : "kindle-neon-dot--off"}`}
      style={
        {
          "--kindle-neon-core": core,
          "--kindle-neon-glow": glow
        } as CSSProperties
      }
      aria-hidden
    />
  );
}

/** Neon breathing dots: red = none, yellow = local, green = on Kindle */
export function KindleTrafficLight(props: {
  locale: Locale;
  hasLocalFile?: boolean;
  notes?: string | null;
  result?: KindleSendFeedback | null;
  className?: string;
}): JSX.Element {
  const { locale, hasLocalFile = false, notes, result, className = "" } = props;
  const light = resolveKindleDeliveryLight({
    hasLocalFile,
    notes,
    session: result ?? null
  });
  const detail = result?.kindle_detail ?? parseKindleDetailFromNotes(notes);
  const title = kindleDeliveryTooltip(locale, light, detail);

  return (
    <span
      className={`inline-flex items-center gap-[7px] ${className}`}
      title={title}
      role="status"
      aria-label={title}
    >
      <KindleNeonDot state="none" active={light === "none"} />
      <KindleNeonDot state="local" active={light === "local"} />
      <KindleNeonDot state="kindle" active={light === "kindle"} />
    </span>
  );
}

export function buildAcquireNotice(locale: Locale, result: BookAcquireResult): BookAcquireNotice {
  const size = formatFileSize(result.file_size_bytes);
  const fmt = result.format.toUpperCase();
  const source =
    result.source === "zlib"
      ? "Z-Library"
      : result.source === "annas"
        ? locale === "zh"
          ? "安娜档案"
          : "Anna's Archive"
        : locale === "zh"
          ? "本地缓存"
          : "cache";

  const saved =
    locale === "zh"
      ? `已保存 ${fmt}${size ? `（${size}）` : ""}，来源 ${source}`
      : `Saved ${fmt}${size ? ` (${size})` : ""} from ${source}`;

  const kindleLine =
    result.kindle_status === "sent"
      ? locale === "zh"
        ? "；已通过邮箱发送到 Kindle"
        : "; emailed to Kindle"
      : result.kindle_status === "failed"
        ? locale === "zh"
          ? `；Kindle 发送失败${result.kindle_detail ? `（${result.kindle_detail}）` : ""}`
          : `; Kindle failed${result.kindle_detail ? ` (${result.kindle_detail})` : ""}`
        : result.kindle_detail
          ? locale === "zh"
            ? `；${result.kindle_detail}`
            : `; ${result.kindle_detail}`
          : "";

  const kind: BookAcquireNotice["kind"] =
    result.kindle_status === "failed" ? "warn" : result.kindle_status === "skipped" ? "warn" : "success";

  return {
    kind,
    message: `${saved}${kindleLine}`,
  };
}

export function BookAcquireNoticeBar(props: {
  locale: Locale;
  notice: BookAcquireNotice | null;
  onDismiss: () => void;
}): JSX.Element | null {
  const { locale, notice, onDismiss } = props;
  if (!notice) {
    return null;
  }

  return (
    <div
      className={`flex shrink-0 items-center justify-between gap-4 border-b px-4 py-2 text-sm ${BAR_STYLES[notice.kind]}`}
      role="status"
    >
      <p className="min-w-0 flex-1 leading-snug">{notice.message}</p>
      <button
        type="button"
        className="shrink-0 text-xs font-medium underline-offset-2 hover:underline"
        onClick={onDismiss}
      >
        {locale === "zh" ? "知道了" : "OK"}
      </button>
    </div>
  );
}

/** Inline traffic light with optional detail text (e.g. acquire success dialog). */
export function KindleStatusBlock(props: {
  locale: Locale;
  result: KindleSendFeedback;
  hasLocalFile?: boolean;
  notes?: string | null;
  compact?: boolean;
}): JSX.Element {
  const { locale, result, hasLocalFile = true, notes, compact } = props;
  const notice = buildKindleSendNotice(locale, result);

  if (compact) {
    return (
      <KindleTrafficLight locale={locale} hasLocalFile={hasLocalFile} notes={notes} result={result} />
    );
  }

  return (
    <div className="flex flex-col items-center gap-2 text-center">
      <KindleTrafficLight locale={locale} hasLocalFile={hasLocalFile} notes={notes} result={result} />
      <p className="max-w-md text-xs leading-relaxed text-muted">{notice.message}</p>
    </div>
  );
}

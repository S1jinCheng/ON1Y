"use client";

import type { BookAcquireResult } from "@/lib/book-types";
import type { Locale } from "@/lib/types";

export type BookAcquireNotice = {
  message: string;
  kind: "success" | "warn" | "error";
};

const BAR_STYLES: Record<BookAcquireNotice["kind"], string> = {
  success:
    "border-emerald-700/35 bg-emerald-700/10 text-emerald-950 dark:border-emerald-500/40 dark:bg-emerald-950/40 dark:text-emerald-100",
  warn: "border-[#722F37]/35 bg-[#722F37]/10 text-[#5a1f28] dark:border-[#a34d5c]/40 dark:bg-[#3d151c] dark:text-[#f2d6da]",
  error:
    "border-[#722F37]/35 bg-[#722F37]/10 text-[#5a1f28] dark:border-[#a34d5c]/40 dark:bg-[#3d151c] dark:text-[#f2d6da]"
};

function formatFileSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function buildAcquireNotice(locale: Locale, result: BookAcquireResult): BookAcquireNotice {
  const size = formatFileSize(result.file_size_bytes);
  const fmt = result.format.toUpperCase();
  const kindle =
    result.kindle_status === "sent"
      ? locale === "zh"
        ? "，已推送 Kindle"
        : ", sent to Kindle"
      : result.kindle_status === "failed"
        ? locale === "zh"
          ? "，Kindle 推送失败"
          : ", Kindle push failed"
        : result.kindle_detail
          ? locale === "zh"
            ? `（${result.kindle_detail}）`
            : ` (${result.kindle_detail})`
          : "";
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

  let message =
    locale === "zh"
      ? `已保存 ${fmt}${size ? `（${size}）` : ""}，来源 ${source}${kindle}`
      : `Saved ${fmt}${size ? ` (${size})` : ""} from ${source}${kindle}`;

  return { message, kind: "success" };
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

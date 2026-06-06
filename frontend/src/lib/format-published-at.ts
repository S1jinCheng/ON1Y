import type { Locale } from "@/lib/types";

function parseDateInput(value: string): Date | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const date = /^\d{4}-\d{2}-\d{2}$/.test(trimmed)
    ? new Date(`${trimmed}T12:00:00`)
    : new Date(trimmed);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatCalendarDate(value: string | null | undefined, locale: Locale): string | null {
  if (!value?.trim()) {
    return null;
  }
  const date = parseDateInput(value);
  if (!date) {
    return null;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "numeric",
    day: "numeric"
  }).format(date);
}

export function formatPublishedAt(value: string | null | undefined, locale: Locale): string | null {
  if (!value?.trim()) {
    return null;
  }
  const date = parseDateInput(value);
  if (!date) {
    return null;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
}

export function formatSourceLine(props: {
  publishedAt?: string | null;
  feedLabel?: string | null;
  source?: string | null;
  hotRank?: number | null;
  heatText?: string | null;
  locale: Locale;
}): string | null {
  const when = formatPublishedAt(props.publishedAt, props.locale);
  const label = props.feedLabel?.trim() || props.source?.trim() || "";
  const rank =
    props.hotRank !== undefined && props.hotRank !== null && props.hotRank > 0
      ? `#${props.hotRank}`
      : "";
  const heat = props.heatText?.trim() || "";
  const hotParts = [rank, heat].filter(Boolean).join(" · ");
  const hotlistLabels: Record<string, string> = {
    "hotlist-zhihu": "知乎",
    "hotlist-economist": "经济学人"
  };
  const sourceLabel = hotlistLabels[label] ?? (
    label.startsWith("hotlist-") ? label.replace(/^hotlist-/, "").toUpperCase() : label
  );
  const meta = [when, hotParts, sourceLabel].filter(Boolean).join(" · ");
  return meta || null;
}

/** Hot-list row: snapshot day + heat (shown under title in compact cards). */
export function formatHotlistMetaLine(props: {
  snapshotDate?: string | null;
  ingestedAt?: string | null;
  heatText?: string | null;
  locale: Locale;
}): string | null {
  let when: string | null = null;
  const snap = props.snapshotDate?.trim();
  if (snap) {
    when = formatCalendarDate(snap, props.locale);
  }
  if (!when) {
    when = formatPublishedAt(props.ingestedAt, props.locale);
  }
  const heat = props.heatText?.trim() || "";
  const parts = [when, heat].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

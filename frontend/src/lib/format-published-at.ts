import type { Locale } from "@/lib/types";

export function formatPublishedAt(value: string | null | undefined, locale: Locale): string | null {
  if (!value?.trim()) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
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
  const sourceLabel = label.startsWith("hotlist-")
    ? label.replace(/^hotlist-/, "").toUpperCase()
    : label;
  const meta = [when, hotParts, sourceLabel].filter(Boolean).join(" · ");
  return meta || null;
}

"use client";

import { ArrowLeft, BarChart3 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getStatsDaily, getStatsOverview } from "@/lib/api";
import { formatCalendarDate } from "@/lib/format-published-at";
import { platformLabel } from "@/lib/platform-label";
import { themeDisplayName, t, type UiKey } from "@/lib/i18n";
import type { StatsOverview } from "@/lib/stats-types";
import type { Locale } from "@/lib/types";

const RANGE_OPTIONS = [30, 90, 180] as const;
const CHART_HEIGHT_PX = 160;

const PLATFORM_COLORS: Record<string, string> = {
  bilibili: "bg-pink-500",
  youtube: "bg-red-500",
  zhihu: "bg-blue-500",
  economist: "bg-amber-600",
  manual: "bg-neutral-500",
  upload: "bg-neutral-400"
};

function barColor(platform: string): string {
  return PLATFORM_COLORS[platform.toLowerCase()] ?? "bg-neutral-400";
}

function kindLabel(locale: Locale, kind: string): string {
  const map: Record<string, UiKey> = {
    video: "statsKindVideo",
    text: "statsKindText",
    unknown: "statsKindUnknown"
  };
  return t(locale, map[kind] ?? "statsKindUnknown");
}

function weekdayLabel(locale: Locale, row: { label_zh: string; label_en: string }): string {
  return locale === "zh" ? row.label_zh : row.label_en;
}

function StatCard(props: { label: string; value: string | number }): JSX.Element {
  return (
    <div className="rounded-lg border border-border bg-panel/50 px-4 py-3">
      <p className="text-xs text-muted">{props.label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{props.value}</p>
    </div>
  );
}

function HorizontalBars(props: {
  rows: Array<{ key: string; label: string; count: number }>;
  max: number;
  colorForKey?: (key: string) => string;
}): JSX.Element {
  const max = props.max || 1;
  return (
    <ul className="space-y-2">
      {props.rows.map((row) => (
        <li key={row.key}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="truncate pr-2 text-neutral-700">{row.label}</span>
            <span className="shrink-0 tabular-nums text-neutral-500">{row.count}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-neutral-100">
            <div
              className={`h-full rounded-full ${props.colorForKey?.(row.key) ?? "bg-neutral-800"}`}
              style={{ width: `${Math.max(4, (row.count / max) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function VerticalBarChart(props: {
  items: Array<{ key: string; label: string; count: number; title?: string }>;
  max: number;
  minBarWidthPx?: number;
  barClassName?: string;
}): JSX.Element {
  const max = props.max || 1;
  const minW = props.minBarWidthPx ?? 10;
  return (
    <div className="overflow-x-auto pb-1">
      <div
        className="flex items-end gap-1"
        style={{ minHeight: CHART_HEIGHT_PX, minWidth: props.items.length * (minW + 4) }}
      >
        {props.items.map((item) => {
          const h =
            item.count > 0
              ? Math.max(8, Math.round((item.count / max) * (CHART_HEIGHT_PX - 24)))
              : 3;
          return (
            <div
              key={item.key}
              className="flex flex-col items-center justify-end"
              style={{ width: minW }}
              title={item.title ?? `${item.label}: ${item.count}`}
            >
              <span className="mb-1 text-[9px] tabular-nums text-neutral-500">
                {item.count > 0 ? item.count : ""}
              </span>
              <div
                className={`w-full rounded-t ${props.barClassName ?? "bg-neutral-800 hover:bg-black"}`}
                style={{ height: h }}
              />
              <span className="mt-1 max-w-full truncate text-[9px] text-neutral-500">
                {item.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function StatsDashboard(props: { locale: Locale }): JSX.Element {
  const { locale } = props;
  const ui = (key: UiKey): string => t(locale, key);
  const [days, setDays] = useState<number>(90);
  const [overview, setOverview] = useState<StatsOverview | undefined>(undefined);
  const [todayTotal, setTodayTotal] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const today = new Date().toISOString().slice(0, 10);
    void Promise.all([getStatsOverview(days), getStatsDaily(today)])
      .then(([stats, daily]) => {
        if (!cancelled) {
          setOverview(stats);
          setTodayTotal(daily.total);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const platformMax = useMemo(
    () => Math.max(1, ...(overview?.by_platform.map((r) => r.count) ?? [1])),
    [overview]
  );
  const kindMax = useMemo(
    () => Math.max(1, ...(overview?.by_content_kind.map((r) => r.count) ?? [1])),
    [overview]
  );
  const themeMax = useMemo(
    () => Math.max(1, ...(overview?.by_theme.map((r) => r.count) ?? [1])),
    [overview]
  );
  const timelineMax = useMemo(
    () => Math.max(1, ...(overview?.timeline.map((d) => d.total) ?? [1])),
    [overview]
  );
  const hourMax = useMemo(
    () => Math.max(1, ...(overview?.by_hour.map((h) => h.count) ?? [1])),
    [overview]
  );
  const weekdayMax = useMemo(
    () => Math.max(1, ...(overview?.by_weekday.map((w) => w.count) ?? [1])),
    [overview]
  );

  const platformRows = useMemo(
    () =>
      (overview?.by_platform ?? []).map((r) => ({
        key: r.platform,
        label: platformLabel(r.platform, locale),
        count: r.count
      })),
    [overview, locale]
  );

  const kindRows = useMemo(
    () =>
      (overview?.by_content_kind ?? []).map((r) => ({
        key: r.content_kind,
        label: kindLabel(locale, r.content_kind),
        count: r.count
      })),
    [overview, locale]
  );

  const themeRows = useMemo(
    () =>
      (overview?.by_theme ?? []).map((r) => ({
        key: r.slug,
        label: themeDisplayName(
          { name_zh: r.name_zh, name_en: r.name_en },
          locale
        ),
        count: r.count
      })),
    [overview, locale]
  );

  const timelineBars = useMemo(() => {
    if (!overview) {
      return [];
    }
    const step = days <= 30 ? 1 : days <= 90 ? 2 : 7;
    const sampled = overview.timeline.filter(
      (_, i) => i % step === 0 || i === overview.timeline.length - 1
    );
    return sampled.map((day) => ({
      key: day.date,
      label: formatCalendarDate(day.date, locale) ?? day.date,
      count: day.total,
      title: `${day.date}: ${day.total}`
    }));
  }, [overview, days, locale]);

  const hourBars = useMemo(
    () =>
      (overview?.by_hour ?? []).map((h) => ({
        key: String(h.hour),
        label: `${String(h.hour).padStart(2, "0")}`,
        count: h.count,
        title: `${h.hour}:00 — ${h.count}`
      })),
    [overview]
  );

  const weekdayBars = useMemo(
    () =>
      (overview?.by_weekday ?? []).map((w) => ({
        key: String(w.weekday),
        label: weekdayLabel(locale, w),
        count: w.count
      })),
    [overview, locale]
  );

  const highlights = overview?.highlights;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-white text-black">
      <header className="shrink-0 border-b border-border px-4 py-3">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-sm hover:bg-soft"
            >
              <ArrowLeft className="h-4 w-4" />
              {ui("statsBack")}
            </Link>
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <BarChart3 className="h-5 w-5" />
              {ui("statsTitle")}
            </h1>
          </div>
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
            {RANGE_OPTIONS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setDays(n)}
                className={`px-3 py-1.5 ${days === n ? "bg-black text-white" : "bg-white hover:bg-soft"}`}
              >
                {ui("statsRangeDays").replace("{n}", String(n))}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-8 px-4 py-6 pb-12">
          {loading ? (
            <p className="text-sm text-muted">{ui("statsLoading")}</p>
          ) : error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : overview ? (
            <>
              <p className="text-xs text-muted">{ui("statsDateBasis")}</p>

              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <StatCard label={ui("statsTotalItems")} value={overview.totals.items} />
                <StatCard
                  label={ui("statsWithPublishTime")}
                  value={overview.totals.with_original_publish_time}
                />
                <StatCard label={ui("statsInRange")} value={overview.totals.in_range} />
                {highlights?.busiest_day ? (
                  <StatCard
                    label={ui("statsBusiestDay")}
                    value={`${formatCalendarDate(highlights.busiest_day, locale) ?? highlights.busiest_day} (${highlights.busiest_day_count})`}
                  />
                ) : null}
                {highlights?.peak_hour != null ? (
                  <StatCard
                    label={ui("statsPeakHour")}
                    value={`${String(highlights.peak_hour).padStart(2, "0")}:00 (${highlights.peak_hour_count})`}
                  />
                ) : null}
                {highlights?.peak_weekday != null ? (
                  <StatCard
                    label={ui("statsPeakWeekday")}
                    value={`${
                      weekdayLabel(
                        locale,
                        overview.by_weekday[highlights.peak_weekday] ?? {
                          label_zh: "",
                          label_en: ""
                        }
                      )
                    } (${highlights.peak_weekday_count})`}
                  />
                ) : null}
              </div>

              <section className="rounded-lg border border-border p-4">
                <h2 className="mb-1 text-sm font-semibold">{ui("statsTimeline")}</h2>
                <p className="mb-3 text-xs text-muted">{ui("statsTimelineHint")}</p>
                {overview.totals.in_range > 0 ? (
                  <VerticalBarChart
                    items={timelineBars}
                    max={timelineMax}
                    minBarWidthPx={days <= 30 ? 14 : 8}
                  />
                ) : (
                  <p className="text-sm text-muted">{ui("statsNoTimelineData")}</p>
                )}
                <div className="mt-2 flex justify-between text-[10px] text-muted">
                  <span>{overview.start_date}</span>
                  <span>{overview.end_date}</span>
                </div>
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section className="rounded-lg border border-border p-4">
                  <h2 className="mb-3 text-sm font-semibold">{ui("statsByHour")}</h2>
                  <VerticalBarChart items={hourBars} max={hourMax} minBarWidthPx={14} />
                </section>
                <section className="rounded-lg border border-border p-4">
                  <h2 className="mb-3 text-sm font-semibold">{ui("statsByWeekday")}</h2>
                  <VerticalBarChart items={weekdayBars} max={weekdayMax} minBarWidthPx={36} />
                </section>
              </div>

              {overview.timeline_peaks.length > 0 ? (
                <section className="rounded-lg border border-border p-4">
                  <h2 className="mb-3 text-sm font-semibold">{ui("statsTimelinePeaks")}</h2>
                  <ul className="space-y-1.5 text-sm">
                    {overview.timeline_peaks.map((peak) => (
                      <li key={peak.date} className="flex justify-between tabular-nums">
                        <span className="text-neutral-800">{peak.date}</span>
                        <span className="font-medium">{peak.total}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section className="rounded-lg border border-border p-4">
                <h2 className="mb-3 text-sm font-semibold">{ui("statsDailyPreview")}</h2>
                <p className="text-3xl font-semibold tabular-nums">
                  {todayTotal === 0 ? ui("statsDailyEmpty") : todayTotal}
                </p>
              </section>

              <div className="grid gap-6 md:grid-cols-2">
                <section className="rounded-lg border border-border p-4">
                  <h2 className="mb-3 text-sm font-semibold">{ui("statsByPlatform")}</h2>
                  <HorizontalBars
                    rows={platformRows}
                    max={platformMax}
                    colorForKey={(key) => barColor(key)}
                  />
                </section>
                <section className="rounded-lg border border-border p-4">
                  <h2 className="mb-3 text-sm font-semibold">{ui("statsByKind")}</h2>
                  <HorizontalBars rows={kindRows} max={kindMax} />
                </section>
              </div>

              <section className="rounded-lg border border-border p-4">
                <h2 className="mb-3 text-sm font-semibold">{ui("statsByTheme")}</h2>
                <HorizontalBars rows={themeRows.slice(0, 16)} max={themeMax} />
              </section>
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
}

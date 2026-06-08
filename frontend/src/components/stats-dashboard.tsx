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
const CHART_HEIGHT_PX = 148;

/** Chart accents only — UI stays neutral B/W/gray */
const CHART = {
  burgundy: "#722F37",
  midnight: "#0f1d32",
  forest: "#1e4d3a",
  gray: "#a1a1aa"
} as const;

const CHART_CYCLE = [CHART.burgundy, CHART.midnight, CHART.forest] as const;

const PLATFORM_COLOR: Record<string, string> = {
  bilibili: CHART.burgundy,
  youtube: CHART.midnight,
  zhihu: "#2a3f5c",
  economist: CHART.forest,
  manual: CHART.gray,
  upload: "#d4d4d8"
};

const KIND_COLOR: Record<string, string> = {
  video: CHART.burgundy,
  text: CHART.forest,
  unknown: CHART.gray
};

function localTodayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function chartColor(key: string, index: number): string {
  return PLATFORM_COLOR[key.toLowerCase()] ?? CHART_CYCLE[index % CHART_CYCLE.length];
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
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <p className="text-xs text-muted">{props.label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-foreground sm:text-2xl">{props.value}</p>
    </div>
  );
}

function DonutChart(props: {
  segments: Array<{ key: string; label: string; count: number; color: string }>;
}): JSX.Element {
  const total = props.segments.reduce((sum, s) => sum + s.count, 0);
  if (total <= 0) {
    return <p className="text-sm text-muted">—</p>;
  }
  let acc = 0;
  const gradient = props.segments
    .map((seg) => {
      const start = (acc / total) * 100;
      acc += seg.count;
      const end = (acc / total) * 100;
      return `${seg.color} ${start}% ${end}%`;
    })
    .join(", ");

  return (
    <div className="flex flex-wrap items-center gap-6">
      <div
        className="relative h-28 w-28 shrink-0 rounded-full"
        style={{ background: `conic-gradient(${gradient})` }}
        aria-hidden
      >
        <div className="absolute inset-[18%] rounded-full bg-surface" />
      </div>
      <ul className="min-w-[10rem] flex-1 space-y-1.5 text-xs">
        {props.segments.map((seg) => (
          <li key={seg.key} className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-foreground/90">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: seg.color }} />
              <span className="truncate">{seg.label}</span>
            </span>
            <span className="shrink-0 tabular-nums text-muted">
              {seg.count}
              <span className="ml-1 text-[10px]">({Math.round((seg.count / total) * 100)}%)</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HorizontalBars(props: {
  rows: Array<{ key: string; label: string; count: number }>;
  max: number;
  colorForKey?: (key: string, index: number) => string;
}): JSX.Element {
  const max = props.max || 1;
  return (
    <ul className="space-y-2.5">
      {props.rows.map((row, index) => (
        <li key={row.key}>
          <div className="mb-1 flex justify-between gap-2 text-xs">
            <span className="truncate text-foreground">{row.label}</span>
            <span className="shrink-0 tabular-nums text-muted">{row.count}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(4, (row.count / max) * 100)}%`,
                backgroundColor: props.colorForKey?.(row.key, index) ?? CHART.midnight
              }}
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
  barColor?: string;
}): JSX.Element {
  const max = props.max || 1;
  const minW = props.minBarWidthPx ?? 10;
  const fill = props.barColor ?? CHART.midnight;
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
              <span className="mb-1 text-[9px] tabular-nums text-muted">
                {item.count > 0 ? item.count : ""}
              </span>
              <div className="w-full rounded-t" style={{ height: h, backgroundColor: fill }} />
              <span className="mt-1 max-w-full truncate text-[9px] text-muted">{item.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Panel(props: { title: string; hint?: string; children: React.ReactNode }): JSX.Element {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-foreground">{props.title}</h2>
      {props.hint ? <p className="mt-1 text-[11px] text-muted">{props.hint}</p> : null}
      <div className="mt-3">{props.children}</div>
    </section>
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
    void (async () => {
      try {
        const stats = await getStatsOverview(days);
        if (cancelled) {
          return;
        }
        setOverview(stats);
        try {
          const daily = await getStatsDaily(localTodayIso());
          if (!cancelled) {
            setTodayTotal(daily.total);
          }
        } catch {
          if (!cancelled) {
            setTodayTotal(undefined);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [days]);

  const platformMax = useMemo(
    () => Math.max(1, ...(overview?.by_platform.map((r) => r.count) ?? [1])),
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
      (overview?.by_platform ?? []).map((r, i) => ({
        key: r.platform,
        label: platformLabel(r.platform, locale),
        count: r.count,
        color: chartColor(r.platform, i)
      })),
    [overview, locale]
  );

  const kindRows = useMemo(
    () =>
      (overview?.by_content_kind ?? []).map((r) => ({
        key: r.content_kind,
        label: kindLabel(locale, r.content_kind),
        count: r.count,
        color: KIND_COLOR[r.content_kind] ?? CHART.gray
      })),
    [overview, locale]
  );

  const themeRows = useMemo(
    () =>
      (overview?.by_theme ?? []).map((r, i) => ({
        key: r.slug,
        label: themeDisplayName({ name_zh: r.name_zh, name_en: r.name_en }, locale),
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
      label: formatCalendarDate(day.date, locale) ?? day.date.slice(5),
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
  const peakWeekdayRow =
    highlights?.peak_weekday != null
      ? overview?.by_weekday.find((w) => w.weekday === highlights.peak_weekday)
      : undefined;

  const todayLabel =
    todayTotal === undefined
      ? "—"
      : todayTotal === 0
        ? ui("statsDailyEmpty")
        : String(todayTotal);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-sm text-foreground hover:bg-soft"
            >
              <ArrowLeft className="h-4 w-4" />
              {ui("statsBack")}
            </Link>
            <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <BarChart3 className="h-5 w-5 text-muted" />
              {ui("statsTitle")}
            </h1>
          </div>
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
            {RANGE_OPTIONS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setDays(n)}
                className={`px-3 py-1.5 transition-colors ${
                  days === n
                    ? "bg-foreground text-background"
                    : "bg-surface text-muted hover:bg-soft hover:text-foreground"
                }`}
              >
                {ui("statsRangeDays").replace("{n}", String(n))}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 pb-12">
          {loading ? (
            <p className="text-sm text-muted">{ui("statsLoading")}</p>
          ) : error ? (
            <p className="rounded-lg border border-border bg-soft px-3 py-2 text-sm text-foreground">
              {ui("statsLoadFailed")}: {error}
            </p>
          ) : overview ? (
            <>
              <p className="text-xs text-muted">{ui("statsDateBasis")}</p>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <StatCard label={ui("statsTotalItems")} value={overview.totals.items} />
                <StatCard
                  label={ui("statsWithPublishTime")}
                  value={overview.totals.with_original_publish_time}
                />
                <StatCard label={ui("statsInRange")} value={overview.totals.in_range} />
                {highlights?.busiest_day ? (
                  <StatCard
                    label={ui("statsBusiestDay")}
                    value={`${formatCalendarDate(highlights.busiest_day, locale) ?? highlights.busiest_day} · ${highlights.busiest_day_count}`}
                  />
                ) : null}
                {highlights?.peak_hour != null ? (
                  <StatCard
                    label={ui("statsPeakHour")}
                    value={`${String(highlights.peak_hour).padStart(2, "0")}:00 · ${highlights.peak_hour_count}`}
                  />
                ) : null}
                {peakWeekdayRow && highlights?.peak_weekday_count ? (
                  <StatCard
                    label={ui("statsPeakWeekday")}
                    value={`${weekdayLabel(locale, peakWeekdayRow)} · ${highlights.peak_weekday_count}`}
                  />
                ) : null}
              </div>

              <Panel title={ui("statsTimeline")} hint={ui("statsTimelineHint")}>
                {overview.totals.in_range > 0 ? (
                  <VerticalBarChart
                    items={timelineBars}
                    max={timelineMax}
                    minBarWidthPx={days <= 30 ? 14 : 8}
                    barColor={CHART.burgundy}
                  />
                ) : (
                  <p className="text-sm text-muted">{ui("statsNoTimelineData")}</p>
                )}
                <div className="mt-2 flex justify-between text-[10px] text-muted">
                  <span>{overview.start_date}</span>
                  <span>{overview.end_date}</span>
                </div>
              </Panel>

              <div className="grid gap-6 lg:grid-cols-2">
                <Panel title={ui("statsByHour")}>
                  <VerticalBarChart
                    items={hourBars}
                    max={hourMax}
                    minBarWidthPx={14}
                    barColor={CHART.midnight}
                  />
                </Panel>
                <Panel title={ui("statsByWeekday")}>
                  <VerticalBarChart
                    items={weekdayBars}
                    max={weekdayMax}
                    minBarWidthPx={36}
                    barColor={CHART.forest}
                  />
                </Panel>
              </div>

              <div className="grid gap-6 md:grid-cols-2">
                <Panel title={ui("statsByPlatform")}>
                  <DonutChart segments={platformRows} />
                </Panel>
                <Panel title={ui("statsByKind")}>
                  <DonutChart segments={kindRows} />
                </Panel>
              </div>

              {overview.timeline_peaks.length > 0 ? (
                <Panel title={ui("statsTimelinePeaks")}>
                  <ul className="divide-y divide-border text-sm">
                    {overview.timeline_peaks.map((peak) => (
                      <li key={peak.date} className="flex justify-between py-2 tabular-nums">
                        <span>{peak.date}</span>
                        <span className="font-medium">{peak.total}</span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              ) : null}

              <Panel title={ui("statsDailyPreview")}>
                <p className="text-3xl font-semibold tabular-nums">{todayLabel}</p>
              </Panel>

              <Panel title={ui("statsByTheme")}>
                <HorizontalBars
                  rows={themeRows.slice(0, 16)}
                  max={themeMax}
                  colorForKey={(_, i) => CHART_CYCLE[i % CHART_CYCLE.length]}
                />
              </Panel>
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
}

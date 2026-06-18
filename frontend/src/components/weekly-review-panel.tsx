"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getWeeklyReview } from "@/lib/api";
import { formatCalendarDate } from "@/lib/format-published-at";
import { platformLabel } from "@/lib/platform-label";
import { themeDisplayName, t, type UiKey } from "@/lib/i18n";
import type { WeeklyReview } from "@/lib/stats-types";
import type { Locale } from "@/lib/types";

const CHART_HEIGHT_PX = 120;

function Panel(props: { title: string; children: React.ReactNode; hint?: string }): JSX.Element {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-medium text-foreground">{props.title}</h2>
      {props.hint ? <p className="mt-0.5 text-xs text-muted">{props.hint}</p> : null}
      <div className="mt-3">{props.children}</div>
    </section>
  );
}

export function WeeklyReviewPanel(props: { locale: Locale }): JSX.Element {
  const { locale } = props;
  const ui = (key: UiKey): string => t(locale, key);
  const [weekOffset, setWeekOffset] = useState(0);
  const [review, setReview] = useState<WeeklyReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getWeeklyReview(weekOffset)
      .then((data) => {
        if (!cancelled) {
          setReview(data);
        }
      })
      .catch((err: unknown) => {
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
  }, [weekOffset]);

  const weekLabel = useMemo(() => {
    if (!review) {
      return "";
    }
    const start = formatCalendarDate(review.week_start, locale) ?? review.week_start;
    const end = formatCalendarDate(review.week_end, locale) ?? review.week_end;
    return `${start} — ${end}`;
  }, [review, locale]);

  const maxDaily = useMemo(() => {
    if (!review) {
      return 0;
    }
    return Math.max(1, ...review.reading.daily.map((d) => d.total));
  }, [review]);

  const delta = review?.comparison.published_delta ?? 0;
  const deltaText =
    delta === 0
      ? ui("weeklyDeltaFlat")
      : delta > 0
        ? ui("weeklyDeltaUp").replace("{n}", String(delta))
        : ui("weeklyDeltaDown").replace("{n}", String(Math.abs(delta)));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">{ui("weeklyTitle")}</h2>
          <p className="text-xs text-muted">{ui("weeklySubtitle")}</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setWeekOffset((v) => v - 1)}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border hover:bg-soft"
            aria-label={ui("weeklyPrev")}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[10rem] px-2 text-center text-xs text-muted">{weekLabel}</span>
          <button
            type="button"
            disabled={weekOffset >= 0}
            onClick={() => setWeekOffset((v) => Math.min(0, v + 1))}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border hover:bg-soft disabled:opacity-40"
            aria-label={ui("weeklyNext")}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted">{ui("statsLoading")}</p>
      ) : error ? (
        <p className="rounded-lg border border-border bg-soft px-3 py-2 text-sm text-muted">
          {ui("statsLoadFailed")}
        </p>
      ) : review ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-surface px-4 py-3">
              <p className="text-xs text-muted">{ui("weeklyPublished")}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{review.reading.published_total}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface px-4 py-3">
              <p className="text-xs text-muted">{ui("weeklyMarkedRead")}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{review.reading.marked_read}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface px-4 py-3">
              <p className="text-xs text-muted">{ui("weeklyNotes")}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{review.notes.updated_count}</p>
            </div>
            <div className="rounded-lg border border-border bg-surface px-4 py-3">
              <p className="text-xs text-muted">{ui("weeklyVsLast")}</p>
              <p className="mt-1 text-sm font-medium text-foreground">{deltaText}</p>
            </div>
          </div>

          <Panel title={ui("weeklyDailyChart")}>
            <div className="flex items-end gap-1.5" style={{ height: CHART_HEIGHT_PX }}>
              {review.reading.daily.map((day) => (
                <div key={day.date} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                  <div
                    className="w-full max-w-[2.5rem] rounded-t bg-foreground/80"
                    style={{
                      height: `${Math.max(4, Math.round((day.total / maxDaily) * (CHART_HEIGHT_PX - 24)))}px`
                    }}
                    title={`${day.date}: ${day.total}`}
                  />
                  <span className="text-[9px] tabular-nums text-muted">
                    {day.date.slice(5).replace("-", "/")}
                  </span>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title={ui("weeklyByPlatform")}>
              {review.reading.by_platform.length === 0 ? (
                <p className="text-sm text-muted">{ui("weeklyEmpty")}</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {review.reading.by_platform.map((row) => (
                    <li key={row.platform} className="flex justify-between gap-2">
                      <span>{platformLabel(row.platform, locale)}</span>
                      <span className="tabular-nums text-muted">{row.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title={ui("weeklyByTheme")}>
              {review.reading.by_theme.length === 0 ? (
                <p className="text-sm text-muted">{ui("weeklyEmpty")}</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {review.reading.by_theme.map((row) => (
                    <li key={row.slug} className="flex justify-between gap-2">
                      <span className="truncate">{themeDisplayName(row, locale)}</span>
                      <span className="shrink-0 tabular-nums text-muted">{row.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <Panel title={ui("weeklyNoteList")} hint={ui("weeklyNoteHint")}>
            {review.notes.items.length === 0 ? (
              <p className="text-sm text-muted">{ui("weeklyNoNotes")}</p>
            ) : (
              <ul className="space-y-2">
                {review.notes.items.map((item) => (
                  <li key={item.raw_id} className="rounded-md border border-border px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Link href={`/?raw=${item.raw_id}`} className="text-sm font-medium hover:underline">
                        {item.title || `#${item.raw_id}`}
                      </Link>
                      <span className="text-[10px] text-muted">
                        {platformLabel(item.platform, locale)}
                      </span>
                    </div>
                    {item.note_preview ? (
                      <p className="mt-1 line-clamp-2 text-xs text-muted">{item.note_preview}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </>
      ) : null}
    </section>
  );
}

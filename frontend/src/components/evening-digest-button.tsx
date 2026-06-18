"use client";

import { Bell, ChevronLeft, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import {
  getEveningDigest,
  getEveningDigestArchive,
  getEveningDigestStatus,
  markEveningDigestRead
} from "@/lib/api";
import { formatCalendarDate } from "@/lib/format-published-at";
import type { EveningDigest, EveningDigestStatus } from "@/lib/digest-types";
import { isEveningDigestPending } from "@/lib/digest-types";
import { platformLabel } from "@/lib/platform-label";
import { themeDisplayName, t, type UiKey } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

const PANEL_ID = "evening-digest-portal";

export function EveningDigestButton(props: { locale: Locale }): JSX.Element {
  const { locale } = props;
  const ui = (key: UiKey): string => t(locale, key);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<EveningDigestStatus | null>(null);
  const [historyDates, setHistoryDates] = useState<string[]>([]);
  const [viewDay, setViewDay] = useState<string | null>(null);
  const [digest, setDigest] = useState<EveningDigest | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const today = status?.today ?? null;
  const viewingToday = viewDay === null || viewDay === today;

  const refreshStatus = useCallback(() => {
    void getEveningDigestStatus()
      .then((s) => setStatus(s))
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 60_000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  const loadDigest = useCallback(
    async (day: string | null) => {
      setLoading(true);
      setPendingMessage(null);
      setError(false);
      setDigest(null);
      try {
        const doc = await getEveningDigest(day ?? undefined);
        if (isEveningDigestPending(doc)) {
          setPendingMessage(
            doc.reason === "before_digest_hour"
              ? ui("eveningDigestPending")
              : ui("eveningDigestNotGenerated")
          );
          return;
        }
        setDigest(doc);
        const isToday = day === null || day === today;
        if (isToday && doc.unread && doc.digest_date) {
          const read = await markEveningDigestRead(doc.digest_date);
          setDigest(read);
          refreshStatus();
        }
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [refreshStatus, today, ui]
  );

  const openPanel = useCallback(() => {
    setOpen(true);
    setViewDay(null);
    void getEveningDigestArchive()
      .then((arch) => setHistoryDates(arch.dates))
      .catch(() => setHistoryDates([]));
    void loadDigest(null);
  }, [loadDigest]);

  const selectDay = useCallback(
    (day: string) => {
      setViewDay(day);
      void loadDigest(day);
    },
    [loadDigest]
  );

  const pastDates = useMemo(
    () => historyDates.filter((d) => d !== today),
    [historyDates, today]
  );

  const dateLabel = useMemo(() => {
    if (!digest?.digest_date) {
      if (viewDay) {
        return formatCalendarDate(viewDay, locale) ?? viewDay;
      }
      return today ? formatCalendarDate(today, locale) ?? today : "";
    }
    return formatCalendarDate(digest.digest_date, locale) ?? digest.digest_date;
  }, [digest, viewDay, today, locale]);

  const statusUnread = Boolean(status?.today_unread);

  return (
    <>
      <button
        type="button"
        onClick={() => openPanel()}
        className="relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-surface hover:bg-soft"
        aria-label={ui("eveningDigestTitle")}
        title={ui("eveningDigestTitle")}
      >
        <Bell className="h-4 w-4" />
        {statusUnread ? (
          <span
            className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-background"
            aria-hidden
          />
        ) : null}
      </button>

      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              id={PANEL_ID}
              className="fixed inset-0 z-[80] flex items-start justify-center bg-black/40 p-4 pt-[10vh]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="evening-digest-heading"
              onClick={() => setOpen(false)}
            >
              <div
                className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-surface shadow-lg"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="sticky top-0 z-10 border-b border-border bg-surface px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      {viewDay && !viewingToday ? (
                        <button
                          type="button"
                          onClick={() => {
                            setViewDay(null);
                            void loadDigest(null);
                          }}
                          className="mb-1 inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"
                        >
                          <ChevronLeft className="h-3.5 w-3.5" />
                          {ui("eveningDigestToday")}
                        </button>
                      ) : null}
                      <h2 id="evening-digest-heading" className="text-base font-semibold">
                        {ui("eveningDigestTitle")}
                      </h2>
                      {dateLabel ? <p className="text-xs text-muted">{dateLabel}</p> : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => setOpen(false)}
                      className="rounded-md p-1 text-muted hover:bg-soft hover:text-foreground"
                      aria-label={ui("coldStartFloatClose")}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  {viewingToday && pastDates.length > 0 ? (
                    <div className="mt-3">
                      <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted">
                        {ui("eveningDigestHistory")}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {pastDates.slice(0, 12).map((d) => (
                          <button
                            key={d}
                            type="button"
                            onClick={() => selectDay(d)}
                            className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted hover:bg-soft hover:text-foreground"
                          >
                            {formatCalendarDate(d, locale) ?? d}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="space-y-4 px-4 py-4">
                  {loading ? (
                    <p className="text-sm text-muted">{ui("statsLoading")}</p>
                  ) : pendingMessage ? (
                    <p className="text-sm text-muted">{pendingMessage}</p>
                  ) : error ? (
                    <p className="text-sm text-muted">{ui("eveningDigestLoadFailed")}</p>
                  ) : digest ? (
                    <DigestBody digest={digest} locale={locale} ui={ui} onClose={() => setOpen(false)} />
                  ) : null}
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}

function DigestBody(props: {
  digest: EveningDigest;
  locale: Locale;
  ui: (key: UiKey) => string;
  onClose: () => void;
}): JSX.Element {
  const { digest, locale, ui, onClose } = props;
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label={ui("eveningDigestPublished")} value={digest.stats.published_total} />
        <Stat label={ui("eveningDigestRead")} value={digest.stats.marked_read} />
        <Stat label={ui("eveningDigestNotes")} value={digest.stats.notes_saved} />
        <Stat label={ui("eveningDigestUnread")} value={digest.stats.unread_total} />
      </div>

      {digest.llm_summary ? (
        <section className="rounded-md border border-border bg-soft/50 px-3 py-3">
          <p className="mb-2 text-xs font-medium text-muted">{ui("eveningDigestSummary")}</p>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
            {digest.llm_summary}
          </div>
        </section>
      ) : digest.llm_error === "llm_not_configured" ? (
        <p className="text-xs text-muted">{ui("eveningDigestNoLlm")}</p>
      ) : null}

      {digest.stats.highlights.length > 0 ? (
        <section>
          <p className="mb-2 text-xs font-medium text-muted">{ui("eveningDigestHighlights")}</p>
          <ul className="space-y-2">
            {digest.stats.highlights.map((item) => (
              <li key={item.raw_id} className="rounded-md border border-border px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link
                    href={`/?raw=${item.raw_id}`}
                    className="text-sm font-medium hover:underline"
                    onClick={onClose}
                  >
                    {item.title || `#${item.raw_id}`}
                  </Link>
                  <span className="text-[10px] text-muted">
                    {platformLabel(item.platform, locale)}
                    {item.is_read ? ` · ${ui("eveningDigestReadBadge")}` : ""}
                  </span>
                </div>
                {item.summary ? (
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{item.summary}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {digest.stats.by_theme.length > 0 ? (
        <section>
          <p className="mb-2 text-xs font-medium text-muted">{ui("weeklyByTheme")}</p>
          <ul className="space-y-1 text-sm">
            {digest.stats.by_theme.map((row) => (
              <li key={row.slug} className="flex justify-between gap-2">
                <span className="truncate">{themeDisplayName(row, locale)}</span>
                <span className="tabular-nums text-muted">{row.count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function Stat(props: { label: string; value: number }): JSX.Element {
  return (
    <div className="rounded-md border border-border px-2 py-2 text-center">
      <p className="text-[10px] text-muted">{props.label}</p>
      <p className="text-lg font-semibold tabular-nums">{props.value}</p>
    </div>
  );
}

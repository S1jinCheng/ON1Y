"use client";

import { Bell, ChevronLeft, ExternalLink, X } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown, { type Components } from "react-markdown";

import {
  getEveningDigest,
  getEveningDigestArchive,
  getEveningDigestStatus,
  markEveningDigestRead
} from "@/lib/api";
import { formatCalendarDate } from "@/lib/format-published-at";
import type { EveningDigest, EveningDigestStatus } from "@/lib/digest-types";
import { isEveningDigestPending } from "@/lib/digest-types";
import { t, type UiKey } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

const PANEL_ID = "evening-digest-portal";

export function looksLikeMarkdownDigest(text: string): boolean {
  return /(^|\n)\s{0,3}(#|##|###)\s+|(\*\*[^*]+\*\*)|(^|\n)\s*-\s+/m.test(text);
}

function isQuoteAttribution(children: React.ReactNode): boolean {
  if (!Array.isArray(children) || children.length !== 1) {
    return false;
  }
  const first = children[0];
  if (typeof first !== "string") {
    return false;
  }
  const trimmed = first.trimStart();
  return trimmed.startsWith("—") || trimmed.startsWith("-");
}

function textFromChildren(children: React.ReactNode): string {
  if (typeof children === "string") {
    return children;
  }
  if (Array.isArray(children)) {
    return children
      .map((node) => (typeof node === "string" ? node : ""))
      .join("")
      .trim();
  }
  return "";
}

function isDetailLine(children: React.ReactNode): boolean {
  const text = textFromChildren(children);
  return text.startsWith("细节：") || text.startsWith("Details:");
}

function isSourceTokenLink(children: React.ReactNode): boolean {
  const text = textFromChildren(children).toLowerCase();
  return text === "ref" || text === "source" || text === "🔍";
}

const digestMarkdownComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 text-2xl font-semibold leading-snug tracking-tight text-foreground">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-5 mb-2 text-lg font-semibold leading-snug text-foreground">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-4 mb-2 text-base font-semibold leading-snug text-foreground">{children}</h3>
  ),
  p: ({ children }) =>
    isQuoteAttribution(children) ? (
      <p className="my-1 text-[11px] leading-relaxed text-muted">{children}</p>
    ) : isDetailLine(children) ? (
      <p className="my-1 text-[13px] leading-6 text-muted">{children}</p>
    ) : (
      <p className="my-2 text-[15px] leading-7 text-foreground">{children}</p>
    ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 italic text-muted">{children}</blockquote>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 text-[15px]">{children}</ul>,
  li: ({ children }) =>
    isDetailLine(children) ? (
      <li className="text-[13px] leading-6 text-muted">{children}</li>
    ) : (
      <li className="leading-7">{children}</li>
    ),
  hr: () => <hr className="my-4 border-border" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={
        isSourceTokenLink(children)
          ? "ml-1 inline-flex items-center align-baseline no-underline opacity-70 hover:opacity-100"
          : "text-blue-500 underline underline-offset-2 hover:text-blue-600"
      }
      aria-label={isSourceTokenLink(children) ? "Open source" : undefined}
    >
      {isSourceTokenLink(children) ? <ExternalLink className="h-3 w-3" /> : children}
    </a>
  ),
  img: ({ src, alt }) => (
    // Allow optional image embeds when digest sources provide media URLs.
    <img src={src || ""} alt={alt || "digest-image"} loading="lazy" className="my-3 max-h-72 w-full rounded-md border border-border object-cover" />
  ),
};

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
                    <DigestBody digest={digest} ui={ui} />
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

export function DigestBody(props: {
  digest: EveningDigest;
  ui: (key: UiKey) => string;
}): JSX.Element {
  const { digest, ui } = props;
  return (
    <>
      {digest.llm_summary ? (
        <section className="rounded-md border border-border bg-soft/50 px-3 py-3 sm:px-4">
          {looksLikeMarkdownDigest(digest.llm_summary) ? (
            <div
              className="max-w-none whitespace-normal break-words text-foreground"
              style={{ fontFamily: "\"Times New Roman\", \"Songti SC\", \"SimSun\", serif" }}
            >
              <ReactMarkdown components={digestMarkdownComponents}>{digest.llm_summary}</ReactMarkdown>
            </div>
          ) : (
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
              {digest.llm_summary}
            </div>
          )}
        </section>
      ) : digest.llm_error === "llm_not_configured" ? (
        <p className="text-xs text-muted">{ui("eveningDigestNoLlm")}</p>
      ) : null}
    </>
  );
}

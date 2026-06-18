"use client";

import { Loader2 } from "lucide-react";
import { createPortal } from "react-dom";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { getReaderContent } from "@/lib/api";
import type { Locale } from "@/lib/types";

const noteHtmlCache = new Map<number, string>();

type NoteHoverPreviewProps = {
  rawId: number;
  /** Skip fetch when note HTML is already available (e.g. active item). */
  noteHtml?: string | null;
  locale: Locale;
  emptyLabel: string;
  children: React.ReactNode;
  className?: string;
};

function hasNoteContent(html: string | null | undefined): boolean {
  if (!html) {
    return false;
  }
  return Boolean(html.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").trim());
}

export function NoteHoverPreview(props: NoteHoverPreviewProps): JSX.Element {
  const { rawId, noteHtml, locale, emptyLabel, children, className } = props;
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number } | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const showTimerRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const loadNote = useCallback(async (): Promise<string> => {
    if (noteHtml !== undefined && hasNoteContent(noteHtml)) {
      return noteHtml;
    }
    const cached = noteHtmlCache.get(rawId);
    if (cached !== undefined) {
      return cached;
    }
    const reader = await getReaderContent(rawId);
    const html = reader.user_note_html ?? "";
    noteHtmlCache.set(rawId, html);
    return html;
  }, [noteHtml, rawId]);

  const scheduleShow = useCallback(() => {
    clearTimers();
    showTimerRef.current = window.setTimeout(() => {
      setOpen(true);
      setLoading(true);
      void loadNote()
        .then((html) => setPreviewHtml(html))
        .catch(() => setPreviewHtml(""))
        .finally(() => setLoading(false));
    }, 280);
  }, [clearTimers, loadNote]);

  const scheduleHide = useCallback(() => {
    clearTimers();
    hideTimerRef.current = window.setTimeout(() => {
      setOpen(false);
      setPreviewHtml(null);
      setLoading(false);
    }, 120);
  }, [clearTimers]);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      return;
    }
    const rect = anchorRef.current.getBoundingClientRect();
    const panelWidth = 300;
    const panelMaxHeight = 220;
    const gap = 10;
    let left = rect.right + gap;
    let top = rect.top;
    if (left + panelWidth > window.innerWidth - 12) {
      left = Math.max(12, rect.left - panelWidth - gap);
    }
    top = Math.max(12, Math.min(top, window.innerHeight - panelMaxHeight - 12));
    setPanelPos({ top, left });
  }, [open]);

  useEffect(() => {
    if (noteHtml !== undefined && hasNoteContent(noteHtml)) {
      noteHtmlCache.set(rawId, noteHtml);
    }
  }, [noteHtml, rawId]);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const panel =
    open && panelPos && typeof document !== "undefined" ? (
      <div
        id={`note-hover-preview-${rawId}`}
        className="fixed z-[220] w-[min(300px,calc(100vw-24px))] overflow-hidden rounded-lg border border-border bg-surface shadow-on1y"
        style={{ top: panelPos.top, left: panelPos.left }}
        onMouseEnter={() => {
          clearTimers();
          setOpen(true);
        }}
        onMouseLeave={scheduleHide}
      >
        <div className="border-b border-border bg-soft/50 px-2.5 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted">
          {locale === "zh" ? "笔记预览" : "Note preview"}
        </div>
        <div className="max-h-52 overflow-y-auto px-3 py-2 text-xs leading-relaxed text-foreground">
          {loading ? (
            <div className="flex items-center gap-2 py-3 text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {locale === "zh" ? "加载中…" : "Loading…"}
            </div>
          ) : hasNoteContent(previewHtml) ? (
            <div
              className="note-preview-html break-words [&_a]:text-accent [&_a]:underline [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4"
              dangerouslySetInnerHTML={{ __html: previewHtml ?? "" }}
            />
          ) : (
            <p className="py-2 text-muted">{emptyLabel}</p>
          )}
        </div>
      </div>
    ) : null;

  return (
    <>
      <span
        ref={anchorRef}
        className={className}
        onMouseEnter={scheduleShow}
        onMouseLeave={scheduleHide}
        onFocus={scheduleShow}
        onBlur={scheduleHide}
      >
        {children}
      </span>
      {panel ? createPortal(panel, document.body) : null}
    </>
  );
}

export function invalidateNotePreviewCache(rawId: number): void {
  noteHtmlCache.delete(rawId);
}

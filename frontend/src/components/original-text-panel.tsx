"use client";

import { Languages, Loader2, Maximize2, Minimize2 } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  formatOriginalText,
  originalTextToHtml,
  pickLocaleTranscript
} from "@/lib/format-original-text";
import type { Locale } from "@/lib/types";

type OriginalTextPanelProps = {
  bodyText: string;
  locale: Locale;
  emptyLabel: string;
  expandLabel: string;
  collapseLabel: string;
  expanded?: boolean;
  onExpand?: () => void;
  onCollapse?: () => void;
  translatedBodyText?: string | null;
  noSubtitleNotice?: string;
  descriptionFallbackLabel?: string;
  translateLabel?: string;
  translatingLabel?: string;
  onTranslate?: () => Promise<void>;
  markdownText?: string | null;
};

export function OriginalTextPanel(props: OriginalTextPanelProps): JSX.Element {
  const {
    bodyText,
    locale,
    emptyLabel,
    expandLabel,
    collapseLabel,
    expanded = false,
    onExpand,
    onCollapse,
    translatedBodyText,
    noSubtitleNotice,
    descriptionFallbackLabel,
    translateLabel,
    translatingLabel,
    onTranslate,
    markdownText
  } = props;

  const [translating, setTranslating] = useState(false);
  const [viewMode, setViewMode] = useState<"txt" | "md">("txt");

  const picked = pickLocaleTranscript(bodyText, locale, translatedBodyText);
  const cleaned = formatOriginalText(bodyText, { locale, translatedBodyText });
  const html = originalTextToHtml(cleaned);
  const isNoSubtitle = picked.kind === "none";
  const canTranslate = locale === "zh" && picked.kind === "en" && Boolean(onTranslate);
  const hasMarkdown = Boolean((markdownText || "").trim());

  async function handleTranslate(): Promise<void> {
    if (!onTranslate || translating) {
      return;
    }
    setTranslating(true);
    try {
      await onTranslate();
    } finally {
      setTranslating(false);
    }
  }

  if (!bodyText.trim() && !isNoSubtitle) {
    return <p className="text-sm text-muted">{emptyLabel}</p>;
  }

  const readingClass = expanded
    ? "text-[1.05rem] leading-[2] tracking-wide"
    : "text-sm leading-relaxed";

  const scrollClass = expanded
    ? "min-h-0 flex-1 overflow-y-auto shadow-inner scrollbar-thin"
    : "max-h-[min(50vh,28rem)] min-h-[10rem] overflow-y-auto scrollbar-thin";

  return (
    <div className={`flex flex-col ${expanded ? "h-full min-h-0 flex-1" : ""}`}>
      <div className="mb-2 flex shrink-0 flex-wrap items-center justify-end gap-2">
        {hasMarkdown ? (
          <div className="inline-flex overflow-hidden rounded border border-border text-xs">
            <button
              type="button"
              className={`px-2 py-1 ${viewMode === "txt" ? "bg-soft text-foreground" : "text-muted hover:bg-soft"}`}
              onClick={() => setViewMode("txt")}
            >
              TXT
            </button>
            <button
              type="button"
              className={`px-2 py-1 ${viewMode === "md" ? "bg-soft text-foreground" : "text-muted hover:bg-soft"}`}
              onClick={() => setViewMode("md")}
            >
              MD
            </button>
          </div>
        ) : null}
        {canTranslate ? (
          <button
            type="button"
            onClick={() => void handleTranslate()}
            disabled={translating}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft disabled:opacity-60"
          >
            {translating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Languages className="h-3.5 w-3.5" />
            )}
            {translating ? translatingLabel : translateLabel}
          </button>
        ) : null}
        {expanded ? (
          <button
            type="button"
            onClick={onCollapse}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
            title={collapseLabel}
          >
            <Minimize2 className="h-3.5 w-3.5" />
            {collapseLabel}
          </button>
        ) : onExpand ? (
          <button
            type="button"
            onClick={onExpand}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
            title={expandLabel}
          >
            <Maximize2 className="h-3.5 w-3.5" />
            {expandLabel}
          </button>
        ) : null}
      </div>

      {isNoSubtitle && noSubtitleNotice ? (
        <div className="mb-3 shrink-0 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {noSubtitleNotice}
        </div>
      ) : null}

      {isNoSubtitle && descriptionFallbackLabel ? (
        <p className="mb-2 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">
          {descriptionFallbackLabel}
        </p>
      ) : null}

      {viewMode === "md" && hasMarkdown ? (
        <div
          className={`original-reading rounded-md border border-border bg-panel px-5 py-4 text-foreground ${readingClass} ${scrollClass}`}
        >
          <div className="prose prose-sm max-w-none text-foreground prose-p:my-1 prose-p:text-foreground">
            <ReactMarkdown>{markdownText || ""}</ReactMarkdown>
          </div>
        </div>
      ) : cleaned ? (
        <div
          className={`original-reading rounded-md border border-border bg-panel px-5 py-4 text-foreground ${readingClass} ${scrollClass} [&_.original-heading]:mb-3 [&_.original-heading]:mt-5 [&_.original-heading]:font-semibold [&_.original-heading]:text-foreground [&_.original-paragraph]:mb-4 [&_.original-paragraph]:indent-8 [&_.original-paragraph]:text-justify`}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <p className="text-sm text-muted">{emptyLabel}</p>
      )}
    </div>
  );
}

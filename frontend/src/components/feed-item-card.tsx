"use client";

import { MoreVertical, Star, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { themeDisplayName } from "@/lib/i18n";
import { formatSourceLine } from "@/lib/format-published-at";
import { platformLabel } from "@/lib/platform-label";
import type { KnowledgeItem, Locale, ThemeRow } from "@/lib/types";

type FeedItemCardProps = {
  item: KnowledgeItem;
  active: boolean;
  locale: Locale;
  themes: ThemeRow[];
  unknownAuthorLabel: string;
  noSummaryLabel: string;
  moveThemeLabel: string;
  favoriteLabel: string;
  unfavoriteLabel: string;
  deleteLabel: string;
  deleteConfirmLabel: string;
  authorAvatar: React.ReactNode;
  onSelect: () => void;
  onMoveTheme: (themeId: number) => void;
  onToggleFavorite: () => void;
  onDelete: () => void;
};

function SearchHtml(props: {
  html?: string | null;
  fallback: string;
  className?: string;
}): JSX.Element {
  const html = props.html?.trim();
  if (html && html.includes("<mark>")) {
    return (
      <span className={props.className} dangerouslySetInnerHTML={{ __html: html }} />
    );
  }
  return <span className={props.className}>{props.fallback}</span>;
}

export function FeedItemCard(props: FeedItemCardProps): JSX.Element {
  const {
    item,
    active,
    locale,
    themes,
    unknownAuthorLabel,
    noSummaryLabel,
    moveThemeLabel,
    favoriteLabel,
    unfavoriteLabel,
    deleteLabel,
    deleteConfirmLabel,
    authorAvatar,
    onSelect,
    onMoveTheme,
    onToggleFavorite,
    onDelete
  } = props;

  const sourceLine = formatSourceLine({
    publishedAt: item.published_at ?? item.ingested_at,
    feedLabel: item.feed_label,
    source: item.source,
    hotRank: item.hot_rank,
    heatText: item.heat_text,
    locale
  });

  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    function onDocClick(event: MouseEvent): void {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
        setConfirmDelete(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  return (
    <div
      className={`relative rounded-lg border transition-colors ${
        active ? "border-black bg-soft" : "border-border bg-white hover:bg-panel"
      }`}
    >
      <div className="absolute right-1.5 top-1.5 z-10" ref={menuRef}>
        <button
          type="button"
          aria-label="Actions"
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
            setConfirmDelete(false);
          }}
          className="rounded p-1 text-neutral-500 hover:bg-white hover:text-black"
        >
          <MoreVertical className="h-4 w-4" />
        </button>
        {menuOpen ? (
          <div className="absolute right-0 top-full z-50 mt-1 w-44 overflow-hidden rounded-md border border-border bg-white py-1 shadow-lg">
            <p className="px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted">
              {moveThemeLabel}
            </p>
            <div className="max-h-36 overflow-y-auto">
              {themes.map((theme) => (
                <button
                  key={theme.id}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onMoveTheme(theme.id);
                    setMenuOpen(false);
                  }}
                  className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-soft ${
                    item.theme_id === theme.id ? "font-medium text-black" : "text-neutral-700"
                  }`}
                >
                  {themeDisplayName(theme, locale)}
                </button>
              ))}
            </div>
            <div className="my-1 border-t border-border" />
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleFavorite();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-soft"
            >
              <Star
                className={`h-3.5 w-3.5 ${item.starred ? "fill-amber-400 text-amber-500" : ""}`}
              />
              {item.starred ? unfavoriteLabel : favoriteLabel}
            </button>
            {confirmDelete ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-red-600 hover:bg-red-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {deleteConfirmLabel}
              </button>
            ) : (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmDelete(true);
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-red-600 hover:bg-red-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {deleteLabel}
              </button>
            )}
          </div>
        ) : null}
      </div>

      <button type="button" onClick={onSelect} className="w-full p-3 pr-9 text-left">
        <div className="flex gap-3">
          {authorAvatar}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <div className="truncate text-xs font-medium text-neutral-800">
                {item.author.trim() || unknownAuthorLabel}
              </div>
              {item.starred ? (
                <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-500" />
              ) : null}
            </div>
            <div className="mt-0.5 line-clamp-2 text-sm font-medium leading-snug">
              <SearchHtml
                html={item.search_title_html}
                fallback={item.title || item.url}
              />
            </div>
            {sourceLine ? (
              <div className="mt-1 text-[11px] text-neutral-500">{sourceLine}</div>
            ) : null}
            <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-neutral-600">
              <SearchHtml
                html={item.search_summary_html}
                fallback={item.summary || item.search_snippet || noSummaryLabel}
              />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1">
              <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-600">
                {platformLabel(item.platform, locale)}
              </span>
              {item.theme ? (
                <span className="rounded border border-black px-1.5 py-0.5 text-[10px] font-medium">
                  {themeDisplayName(item.theme, locale)}
                </span>
              ) : null}
              {item.tags.slice(0, 3).map((tg) => (
                <span
                  key={tg.id}
                  className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-700"
                >
                  #{tg.name}
                </span>
              ))}
            </div>
          </div>
        </div>
      </button>
    </div>
  );
}

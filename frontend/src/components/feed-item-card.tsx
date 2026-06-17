"use client";

import { CheckCircle2, Circle, Forward, NotebookPen, RotateCcw, Star, Trash2 } from "lucide-react";
import { useState } from "react";

import { ContentTypeIndicator } from "@/components/content-type-indicator";
import { ThemeMovePopover } from "@/components/theme-move-popover";
import { formatHotlistMetaLine, formatSourceLine } from "@/lib/format-published-at";
import { feedItemListTagClass } from "@/components/tag-chip-editor";
import { themeDisplayName } from "@/lib/i18n";
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
  batchSelectLabel: string;
  authorAvatar?: React.ReactNode;
  onSelect: () => void;
  onMoveTheme: (themeId: number) => void;
  onToggleFavorite: () => void;
  onDelete: () => void;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelected?: () => void;
  trashMode?: boolean;
  restoreLabel?: string;
  onRestore?: () => void;
  /** Hot list: title (and rank) only — no avatar, author, or summary. */
  compact?: boolean;
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

function tagsWithoutAuthor(item: KnowledgeItem): KnowledgeItem["tags"] {
  const authorKey = item.author.trim().toLowerCase();
  if (!authorKey) {
    return item.tags;
  }
  return item.tags.filter((tg) => tg.name.trim().toLowerCase() !== authorKey);
}

function ActionBtn(props: {
  label: string;
  onClick: (e: React.MouseEvent) => void;
  className?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      aria-label={props.label}
      title={props.label}
      onClick={props.onClick}
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-soft hover:text-foreground ${props.className ?? ""}`}
    >
      {props.children}
    </button>
  );
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
    batchSelectLabel,
    authorAvatar,
    onSelect,
    onMoveTheme,
    onToggleFavorite,
    onDelete,
    selectionMode = false,
    selected = false,
    onToggleSelected,
    trashMode = false,
    restoreLabel = "Restore",
    onRestore,
    compact = false
  } = props;

  const visibleTags = tagsWithoutAuthor(item);

  const hotlistMetaLine = compact
    ? item.platform === "economist" && item.heat_text
      ? locale === "zh"
        ? `出刊 ${item.heat_text}`
        : `Edition ${item.heat_text}`
      : formatHotlistMetaLine({
          snapshotDate: item.snapshot_date,
          ingestedAt: item.ingested_at,
          heatText: item.heat_text,
          locale
        })
    : null;

  const sourceLine = compact
    ? null
    : formatSourceLine({
        publishedAt: item.published_at,
        feedLabel: item.feed_label,
        source: item.source,
        hotRank: item.hot_rank,
        heatText: item.heat_text,
        locale
      });

  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleContentClick(): void {
    if (selectionMode) {
      onToggleSelected?.();
      return;
    }
    onSelect();
  }

  return (
    <div
      className={`flex overflow-hidden rounded-lg border transition-colors ${
        selectionMode && selected
          ? "border-foreground bg-soft ring-1 ring-foreground"
          : active
            ? "border-foreground bg-soft"
            : "border-border bg-surface hover:bg-panel"
      }`}
    >
      <button
        type="button"
        onClick={handleContentClick}
        className="min-w-0 flex-1 p-3 text-left"
      >
        {compact ? (
          <div>
            <div className="flex items-start gap-1.5 text-sm font-medium leading-snug text-foreground">
              <div className="min-w-0 flex-1">
                <SearchHtml
                  html={item.search_title_html}
                  fallback={item.title || item.url}
                />
              </div>
              <ContentTypeIndicator
                contentType={item.content_type}
                platform={item.platform}
                locale={locale}
                className="mt-0.5"
              />
            </div>
            {hotlistMetaLine ? (
              <p className="mt-1 text-[11px] text-muted">{hotlistMetaLine}</p>
            ) : null}
            {visibleTags.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {visibleTags.slice(0, 6).map((tg) => (
                  <span key={tg.id} className={feedItemListTagClass}>
                    #{tg.name}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex gap-3">
            {authorAvatar}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-foreground">
                {item.author.trim() || unknownAuthorLabel}
              </div>
              <div className="mt-0.5 flex items-start gap-1.5 text-sm font-medium leading-snug text-foreground">
                {!item.is_read && !item.read_at ? (
                  <span
                    className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-sky-500"
                    aria-hidden
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <SearchHtml
                    html={item.search_title_html}
                    fallback={item.title || item.url}
                  />
                </div>
                <ContentTypeIndicator
                  contentType={item.content_type}
                  platform={item.platform}
                  locale={locale}
                  className="mt-0.5 shrink-0"
                />
              </div>
              {sourceLine ? (
                <div className="mt-1 text-[11px] text-muted">{sourceLine}</div>
              ) : null}
              <div className="mt-1 text-xs leading-relaxed text-muted">
                <SearchHtml
                  html={item.search_summary_html}
                  fallback={item.summary || item.search_snippet || noSummaryLabel}
                />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                <span className="rounded bg-soft px-1.5 py-0.5 text-[10px] text-muted">
                  {platformLabel(item.platform, locale)}
                </span>
                {item.has_note ? (
                  <span
                    className="inline-flex items-center gap-0.5 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-300"
                    title="Notes"
                  >
                    <NotebookPen className="h-3 w-3" />
                  </span>
                ) : null}
                {item.theme ? (
                  <span className="rounded border border-foreground px-1.5 py-0.5 text-[10px] font-medium text-foreground">
                    {themeDisplayName(item.theme, locale)}
                  </span>
                ) : null}
                {visibleTags.slice(0, 3).map((tg) => (
                  <span key={tg.id} className={feedItemListTagClass}>
                    #{tg.name}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </button>

      <div
        className={`flex shrink-0 flex-col items-center justify-center gap-0 border-l border-border bg-panel/80 ${
          selectionMode ? "w-10 py-2" : "py-1"
        }`}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={() => undefined}
        role="presentation"
      >
        <ActionBtn
          label={batchSelectLabel}
          className={selected ? "text-foreground" : ""}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelected?.();
          }}
        >
          {selected ? (
            <CheckCircle2 className="h-4 w-4 fill-foreground text-background" />
          ) : (
            <Circle className="h-4 w-4" />
          )}
        </ActionBtn>

        {trashMode && !selectionMode ? (
          <ActionBtn
            label={restoreLabel}
            onClick={(e) => {
              e.stopPropagation();
              onRestore?.();
            }}
          >
            <RotateCcw className="h-4 w-4" />
          </ActionBtn>
        ) : !trashMode && !selectionMode ? (
          <>
        <ActionBtn
          label={item.starred ? unfavoriteLabel : favoriteLabel}
          onClick={(e) => {
            e.stopPropagation();
            onToggleFavorite();
          }}
        >
          <Star
            className={`h-4 w-4 ${item.starred ? "fill-amber-400 text-amber-500" : ""}`}
          />
        </ActionBtn>

          <ThemeMovePopover
            themes={themes}
            locale={locale}
            currentThemeId={item.theme_id}
            onSelect={onMoveTheme}
            floatPanel
            trigger={
              <button
                type="button"
                aria-label={moveThemeLabel}
                title={moveThemeLabel}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-soft hover:text-foreground"
              >
                <Forward className="h-4 w-4" />
              </button>
            }
          />

          {confirmDelete ? (
            <ActionBtn
              label={deleteConfirmLabel}
              className="text-red-600 hover:bg-red-500/10 hover:text-red-500"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
                setConfirmDelete(false);
              }}
            >
              <Trash2 className="h-4 w-4" />
            </ActionBtn>
          ) : (
            <ActionBtn
              label={deleteLabel}
              className="hover:text-red-500"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmDelete(true);
              }}
            >
              <Trash2 className="h-4 w-4" />
            </ActionBtn>
          )}
          </>
        ) : null}
      </div>
    </div>
  );
}

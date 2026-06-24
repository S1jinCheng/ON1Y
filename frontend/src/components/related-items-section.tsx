"use client";

import { ThumbsDown } from "lucide-react";

import { ContentTypeIndicator } from "@/components/content-type-indicator";
import { feedItemListTagClass } from "@/components/tag-chip-editor";
import { platformLabel } from "@/lib/platform-label";
import type { KnowledgeItem, Locale } from "@/lib/types";

type RelatedItemsSectionProps = {
  items: KnowledgeItem[];
  locale: Locale;
  titleLabel: string;
  lessRelevantLabel?: string;
  actionLabel?: string;
  onSelect: (rawId: number) => void;
  onLessRelevant?: (toRawId: number) => void;
  onAction?: (toRawId: number) => void;
};

function tagsWithoutAuthor(item: KnowledgeItem): KnowledgeItem["tags"] {
  const authorKey = item.author.trim().toLowerCase();
  if (!authorKey) {
    return item.tags;
  }
  return item.tags.filter((tg) => tg.name.trim().toLowerCase() !== authorKey);
}

export function RelatedItemsSection(props: RelatedItemsSectionProps): JSX.Element | null {
  const { items, locale, titleLabel, lessRelevantLabel, actionLabel, onSelect, onLessRelevant, onAction } =
    props;
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="border-t border-border px-4 py-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
        {titleLabel}
      </p>
      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={item.raw_id}
            className="group flex gap-2 rounded-lg border border-border bg-panel/40 p-2 transition-colors hover:border-muted hover:bg-panel"
          >
            <button
              type="button"
              onClick={() => onSelect(item.raw_id)}
              className="min-w-0 flex-1 text-left"
            >
              <div className="flex items-start gap-1.5">
                <p className="min-w-0 flex-1 text-sm font-medium leading-snug text-foreground line-clamp-2">
                  {item.title || item.url}
                </p>
                <ContentTypeIndicator
                  contentType={item.content_type}
                  platform={item.platform}
                  locale={locale}
                  className="mt-0.5 shrink-0"
                />
              </div>
              {item.summary ? (
                <p className="mt-1 text-xs leading-relaxed text-muted line-clamp-2">
                  {item.summary}
                </p>
              ) : null}
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="rounded bg-soft px-1.5 py-0.5 text-[10px] font-medium text-muted">
                  {platformLabel(item.platform, locale)}
                </span>
                {tagsWithoutAuthor(item).slice(0, 4).map((tg) => (
                  <span key={tg.id} className={feedItemListTagClass}>
                    #{tg.name}
                  </span>
                ))}
              </div>
            </button>
            <div className="mt-0.5 flex shrink-0 items-center gap-1">
              {onAction && actionLabel ? (
                <button
                  type="button"
                  aria-label={actionLabel}
                  title={actionLabel}
                  onClick={() => onAction(item.raw_id)}
                  className="rounded-md px-2 py-1 text-[11px] text-muted transition-colors hover:bg-soft hover:text-foreground"
                >
                  {actionLabel}
                </button>
              ) : null}
              {onLessRelevant && lessRelevantLabel ? (
                <button
                  type="button"
                  aria-label={lessRelevantLabel}
                  title={lessRelevantLabel}
                  onClick={() => onLessRelevant(item.raw_id)}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted opacity-0 transition-opacity hover:bg-soft hover:text-foreground group-hover:opacity-100 focus:opacity-100"
                >
                  <ThumbsDown className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

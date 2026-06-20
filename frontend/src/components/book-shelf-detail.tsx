"use client";

import { BookOpen, ExternalLink, Loader2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ImportanceStars } from "@/components/importance-stars";
import { RelatedItemsSection } from "@/components/related-items-section";
import { RichNoteEditor } from "@/components/rich-note-editor";
import { TagChipEditor } from "@/components/tag-chip-editor";
import {
  deleteBookShelfItem,
  fetchRelatedShelfBooks,
  getTaxonomy,
  postRelatedLessRelevant,
  openLocalPath,
  updateBookShelfItem
} from "@/lib/api";
import { bookCoverSrc } from "@/lib/book-cover";
import type { BookShelfItem, BookStatus } from "@/lib/book-types";
import type { KnowledgeItem, Locale } from "@/lib/types";

const STATUS_OPTIONS: BookStatus[] = ["reading", "read"];

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

function statusLabel(locale: Locale, status: BookStatus): string {
  if (locale === "zh") {
    if (status === "reading") return "在读";
    return "已读";
  }
  if (status === "reading") return "Reading";
  return "Read";
}

function metaLine(item: BookShelfItem): string {
  return [item.author, item.translator, item.publisher].filter(Boolean).join(" / ");
}

type Props = {
  locale: Locale;
  item: BookShelfItem;
  onSaved: (item: BookShelfItem) => void;
  onDeleted: () => void;
  onSelectShelfItem: (id: number) => void;
  onSelectKnowledgeItem: (item: KnowledgeItem) => void;
  onMessage: (msg: string) => void;
};

export function BookShelfDetail(props: Props): JSX.Element {
  const { locale, item, onSaved, onDeleted, onSelectShelfItem, onSelectKnowledgeItem, onMessage } =
    props;
  const [tags, setTags] = useState<string[]>(item.tags ?? []);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [related, setRelated] = useState<KnowledgeItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(true);
  const [relatedLoaded, setRelatedLoaded] = useState(false);
  const [relatedFromRawId, setRelatedFromRawId] = useState<number | null>(item.raw_id ?? null);

  const coverSrc = useMemo(() => bookCoverSrc(item.cover_url), [item.cover_url]);

  useEffect(() => {
    setTags(item.tags ?? []);
  }, [item.id, item.tags]);

  useEffect(() => {
    let cancelled = false;
    void getTaxonomy()
      .then((taxonomy) => {
        if (!cancelled) {
          setTagSuggestions(taxonomy.tags.map((row) => row.name));
        }
      })
      .catch(() => {
        /* optional */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setRelatedFromRawId(item.raw_id ?? null);
  }, [item.id, item.raw_id]);

  useEffect(() => {
    let cancelled = false;
    setRelatedLoading(true);
    setRelatedLoaded(false);
    const timer = window.setTimeout(() => {
      void fetchRelatedShelfBooks(item.id)
        .then((resp) => {
          if (!cancelled) {
            setRelated(resp.items);
            if (resp.from_raw_id != null) {
              setRelatedFromRawId(resp.from_raw_id);
              if (item.raw_id == null) {
                onSaved({ ...item, raw_id: resp.from_raw_id });
              }
            }
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setRelated([]);
            onMessage(error instanceof Error ? error.message : "load related failed");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setRelatedLoading(false);
            setRelatedLoaded(true);
          }
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [item, item.id, item.summary, item.tags, item.raw_id, onMessage, onSaved]);

  const saveTags = useCallback(
    async (next: string[]) => {
      setTags(next);
      try {
        const updated = await updateBookShelfItem(item.id, { tags: next });
        onSaved(updated);
      } catch (error) {
        onMessage(error instanceof Error ? error.message : "save failed");
      }
    },
    [item.id, onMessage, onSaved]
  );

  async function handleStatusChange(next: BookStatus): Promise<void> {
    try {
      const updated = await updateBookShelfItem(item.id, { status: next });
      onSaved(updated);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "update failed");
    }
  }

  async function handleDelete(): Promise<void> {
    if (!window.confirm(L(locale, "从书架移除？", "Remove from shelf?"))) return;
    try {
      await deleteBookShelfItem(item.id);
      onDeleted();
      onMessage(L(locale, "已移除", "Removed"));
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "delete failed");
    }
  }

  async function handleSaveNote(html: string): Promise<void> {
    const updated = await updateBookShelfItem(item.id, { user_note_html: html });
    onSaved(updated);
  }

  async function handleImportanceChange(importance: number | null): Promise<void> {
    const updated = await updateBookShelfItem(item.id, { importance });
    onSaved(updated);
  }

  async function handleRelatedLessRelevant(toRawId: number): Promise<void> {
    const fromRawId = relatedFromRawId ?? item.raw_id;
    if (fromRawId == null) return;
    try {
      await postRelatedLessRelevant(fromRawId, toRawId);
      setRelated((prev) => prev.filter((row) => row.raw_id !== toRawId));
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "feedback failed");
    }
  }

  function handleRelatedSelect(rawId: number): void {
    const row = related.find((entry) => entry.raw_id === rawId);
    if (!row) return;
    const shelfMatch = row.url.match(/^on1y:\/\/books\/shelf\/(\d+)$/);
    if (shelfMatch) {
      onSelectShelfItem(Number(shelfMatch[1]));
      return;
    }
    onSelectKnowledgeItem(row);
  }

  const doubanLink = item.links.find((l) => l.label === "豆瓣" || /douban\.com/i.test(l.url));

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border pb-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <label className="text-xs text-muted">
            {L(locale, "状态", "Status")}
            <select
              value={item.status === "read" ? "read" : "reading"}
              onChange={(e) => void handleStatusChange(e.target.value as BookStatus)}
              className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-sm"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {statusLabel(locale, opt)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void handleDelete()}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-red-600 hover:bg-red-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            {L(locale, "移除", "Remove")}
          </button>
        </div>

        <div className="flex gap-4">
          <div className="w-24 shrink-0">
            {coverSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={coverSrc} alt="" className="h-36 w-24 rounded object-cover" />
            ) : (
              <div className="flex h-36 w-24 items-center justify-center rounded bg-panel text-muted">
                <BookOpen className="h-8 w-8" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold leading-snug">{item.title}</h2>
            {metaLine(item) ? <p className="mt-1 text-sm text-muted">{metaLine(item)}</p> : null}
            {item.cached_format ? (
              <p className="mt-2 inline-block rounded bg-soft px-2 py-0.5 text-xs text-muted">
                {item.cached_format.toUpperCase()}
                {item.local_path ? L(locale, " · 已缓存", " · cached") : ""}
              </p>
            ) : null}
            {item.local_path ? (
              <button
                type="button"
                onClick={() =>
                  void openLocalPath(item.local_path!).catch((error) =>
                    onMessage(error instanceof Error ? error.message : "open failed")
                  )
                }
                className="mt-2 block text-xs text-accent hover:underline"
              >
                {L(locale, "打开本地文件", "Open local file")}
              </button>
            ) : null}
            {doubanLink ? (
              <a
                href={doubanLink.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"
              >
                {L(locale, "豆瓣", "Douban")}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
          </div>
        </div>

        {item.summary ? (
          <div className="mt-4">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">
              {L(locale, "简介", "Summary")}
            </p>
            <p className="text-sm leading-relaxed text-muted line-clamp-6">{item.summary}</p>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-4">
        <div className="mb-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted">
              {L(locale, "标签", "Tags")}
            </p>
            <ImportanceStars
              value={item.importance ?? null}
              onChange={(v) => void handleImportanceChange(v)}
            />
          </div>
          <TagChipEditor
            tags={tags}
            suggestions={tagSuggestions}
            locale={locale}
            onChange={(next) => void saveTags(next)}
          />
        </div>

        <div className="mb-4 min-h-[200px]">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
            {L(locale, "读书笔记", "Reading notes")}
          </p>
          <RichNoteEditor
            value={item.user_note_html ?? ""}
            placeholder={L(locale, "记录读后感、摘抄、想法…", "Notes, quotes, thoughts…")}
            saveLabel={L(locale, "保存笔记", "Save note")}
            onSave={handleSaveNote}
          />
        </div>

        <div className="border-t border-border pt-4">
          {relatedLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              {L(locale, "加载推荐…", "Loading picks…")}
            </div>
          ) : related.length > 0 ? (
            <RelatedItemsSection
              items={related}
              locale={locale}
              titleLabel={L(locale, "相关阅读", "Related reading")}
              lessRelevantLabel={L(locale, "不太相关", "Less relevant")}
              onSelect={handleRelatedSelect}
              onLessRelevant={(toRawId) => void handleRelatedLessRelevant(toRawId)}
            />
          ) : relatedLoaded ? (
            <p className="text-sm text-muted">
              {L(
                locale,
                "暂无相关推荐；给书打标签后更容易匹配库内文章与视频",
                "No related picks yet — add tags to improve matches"
              )}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

"use client";

import {
  BookOpen,
  CheckSquare,
  Download,
  ExternalLink,
  Loader2,
  Plus,
  Search,
  Square,
  Star,
  Trash2,
  X
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { BookShelfCard } from "@/components/book-shelf-card";
import { BookShelfDetail } from "@/components/book-shelf-detail";
import {
  type BookAcquireRequest,
  useBookAcquireConfirm
} from "@/components/book-acquire-confirm-dialog";
import { buildKindleSendNotice, type BookAcquireNotice } from "@/components/book-acquire-notice";

import {
  createBookShelfItem,
  deleteBookShelfItem,
  fetchBookDetail,
  fetchBookSettings,
  fetchBookSources,
  fetchBookShelfItem,
  listBookShelf,
  openLocalPath,
  searchBooks,
  sendBookShelfToKindle,
  updateBookShelfItem
} from "@/lib/api";
import { probeShelfCachedFiles, type ShelfCachedState } from "@/lib/use-shelf-cached-files";
import { readBuiltinToggles, BOOK_ANNAS_BASE, BOOK_ZLIB_BASE } from "@/lib/book-builtin";
import { bookCoverSrc } from "@/lib/book-cover";
import type {
  BookEditionHit,
  BookLink,
  BookSearchHit,
  BookShelfItem,
  BookStatus,
  BookWorkDetail
} from "@/lib/book-types";
import type { Locale, KnowledgeItem } from "@/lib/types";

type BooksListColumnProps = {
  locale: Locale;
  activeId: number | null;
  activeEditionId: string | null;
  manualAdd: boolean;
  onAcquireNotice: (notice: BookAcquireNotice | null) => void;
  onSelect: (item: BookShelfItem) => void;
  onSelectEdition: (edition: BookEditionHit) => void;
  onStartManualAdd: () => void;
  onShelfChanged: () => void;
  onEditionShelfAdded: (item: BookShelfItem) => void;
  onItemUpdated?: (item: BookShelfItem) => void;
  onRemoved?: (id: number) => void;
  onMessage: (msg: string) => void;
};

type BooksDetailColumnProps = {
  locale: Locale;
  item: BookShelfItem | null;
  edition: BookEditionHit | null;
  manualAdd: boolean;
  onAcquireNotice: (notice: BookAcquireNotice | null) => void;
  onSaved: (item: BookShelfItem) => void;
  onDeleted: () => void;
  onCancelManual: () => void;
  onMessage: (msg: string) => void;
  onSelectShelfItem: (id: number) => void;
  onSelectKnowledgeItem: (item: KnowledgeItem) => void;
};

const STATUS_OPTIONS: BookStatus[] = ["reading", "read"];

function statusLabel(locale: Locale, status: BookStatus | "want"): string {
  if (locale === "zh") {
    if (status === "reading") return "在读";
    if (status === "want") return "在读";
    return "已读";
  }
  if (status === "reading" || status === "want") return "Reading";
  return "Read";
}

function editionMetaLine(edition: BookEditionHit): string {
  const parts = [edition.author, edition.translator, edition.publisher, edition.pub_meta].filter(
    Boolean
  );
  return parts.join(" / ");
}

function ratingLabel(edition: BookEditionHit | BookWorkDetail): string {
  if (edition.rating == null) return "";
  const count =
    "rating_count" in edition && edition.rating_count
      ? ` (${edition.rating_count})`
      : "";
  return `${edition.rating.toFixed(1)}${count}`;
}

function editionAcquireRequest(
  edition: BookEditionHit,
  detail: BookWorkDetail | null | undefined,
  addToShelf: boolean
): BookAcquireRequest {
  return {
    title: edition.title,
    author: edition.author ?? detail?.author ?? null,
    translator: edition.translator ?? detail?.translator ?? null,
    publisher: edition.publisher ?? detail?.publisher ?? null,
    isbn: detail?.isbn ?? null,
    douban_url: edition.url,
    cover_url: edition.cover_url ?? detail?.cover_url ?? null,
    add_to_shelf: addToShelf
  };
}

function editionSearchQuery(parts: {
  title: string;
  author?: string | null;
  translator?: string | null;
}): string {
  const bits = [parts.title.trim()];
  if (parts.author?.trim()) {
    bits.push(parts.author.trim());
  }
  if (parts.translator?.trim()) {
    bits.push(parts.translator.trim());
  }
  return bits.filter(Boolean).join(" ");
}

function buildEditionSourceLinks(
  parts: {
    title: string;
    doubanUrl: string;
    author?: string | null;
    translator?: string | null;
  },
  zlibBaseUrl: string,
  toggles: { zlibEnabled: boolean; annasEnabled: boolean }
): BookLink[] {
  const query = editionSearchQuery(parts);
  const encoded = encodeURIComponent(query);
  const base = (zlibBaseUrl || BOOK_ZLIB_BASE).replace(/\/$/, "");
  const links: BookLink[] = [{ label: "豆瓣", url: parts.doubanUrl }];
  if (toggles.zlibEnabled) {
    links.push({ label: "Z-Library", url: `${base}/s/${encoded}` });
  }
  if (toggles.annasEnabled) {
    links.push({ label: "安娜档案", url: `${BOOK_ANNAS_BASE}/search?q=${encoded}` });
  }
  return links;
}

function EditionSourceLinksRow(props: { links: BookLink[] }): JSX.Element | null {
  if (props.links.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {props.links.map((link, index) => (
        <span key={link.label} className="inline-flex items-center gap-2">
          {index > 0 ? <span className="text-[11px] text-muted/35 select-none">·</span> : null}
          <a
            href={link.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-[11px] text-muted underline-offset-2 hover:text-foreground hover:underline"
          >
            {link.label}
            <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
          </a>
        </span>
      ))}
    </div>
  );
}

function doubanUrlFromLinks(links: BookLink[]): string | null {
  for (const link of links) {
    if (link.label === "豆瓣" || link.label.startsWith("豆瓣") || /douban\.com/i.test(link.url)) {
      return link.url;
    }
  }
  return null;
}

function canRestoreShelf(item: BookShelfItem): boolean {
  return Boolean(doubanUrlFromLinks(item.links) || item.links.some((l) => /zlib|annas/i.test(l.url)));
}

function shelfRestoreRequest(item: BookShelfItem): BookAcquireRequest {
  return {
    title: item.title,
    author: item.author,
    translator: item.translator,
    publisher: item.publisher,
    douban_url: doubanUrlFromLinks(item.links),
    cover_url: item.cover_url,
    add_to_shelf: true,
    shelf_item_id: item.id
  };
}

function DoubanDetailBody(props: {
  locale: Locale;
  detail: BookWorkDetail;
  sourceLinks: BookLink[];
  acquiring: boolean;
  onDownload: () => void;
  footerNote?: string;
}): JSX.Element {
  const { locale, detail, sourceLinks, acquiring, onDownload, footerNote } = props;
  return (
    <div className="space-y-4">
      <div>
        <div className="flex gap-4">
          <div className="w-24 shrink-0">
            {detail.cover_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={bookCoverSrc(detail.cover_url)}
                alt=""
                className="h-36 w-24 rounded object-cover"
              />
            ) : (
              <div className="flex h-36 w-24 items-center justify-center rounded bg-panel text-muted">
                <BookOpen className="h-8 w-8" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold leading-snug">{detail.title}</h2>
          {detail.author ? (
            <p className="mt-1 text-sm text-muted">
              {locale === "zh" ? "作者" : "Author"}：{detail.author}
            </p>
          ) : null}
          {detail.translator ? (
            <p className="mt-0.5 text-sm text-muted">
              {locale === "zh" ? "译者" : "Translator"}：{detail.translator}
            </p>
          ) : null}
          {detail.publisher ? (
            <p className="mt-0.5 text-sm text-muted">
              {detail.publisher}
              {detail.pub_date ? ` / ${detail.pub_date}` : ""}
            </p>
          ) : null}
          {detail.isbn ? <p className="mt-0.5 text-xs text-muted">ISBN {detail.isbn}</p> : null}
          {detail.rating != null ? (
            <p className="mt-2 text-sm text-amber-700">★ {ratingLabel(detail)}</p>
          ) : null}
        </div>
        </div>
        <div className="mt-2">
          <EditionSourceLinksRow links={sourceLinks} />
        </div>
      </div>
      {detail.summary ? (
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
            {locale === "zh" ? "内容简介" : "Summary"}
          </h3>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{detail.summary}</p>
        </div>
      ) : null}
      {detail.short_reviews && detail.short_reviews.length > 0 ? (
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
            {locale === "zh" ? "短评" : "Short reviews"}
          </h3>
          <div className="space-y-3">
            {detail.short_reviews.map((review, index) => (
              <div
                key={`${review.author ?? "anon"}-${index}`}
                className="rounded-md border border-border bg-panel p-3"
              >
                <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                  {review.author ? (
                    <span className="text-sm font-medium text-foreground">{review.author}</span>
                  ) : null}
                  {review.published_at ? (
                    <span className="text-xs text-muted">{review.published_at}</span>
                  ) : null}
                </div>
                <p className="text-sm leading-relaxed text-foreground/90">{review.content}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div>
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
          {locale === "zh" ? "获取电子书" : "Get ebook"}
        </h3>
        <button
          type="button"
          disabled={acquiring}
          onClick={() => onDownload()}
          className="flex w-full items-center justify-between rounded-md border border-border bg-panel px-3 py-2 text-sm hover:bg-soft disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            {acquiring ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted" />
            ) : (
              <Download className="h-4 w-4 text-muted" />
            )}
            {locale === "zh" ? "下载电子书" : "Download ebook"}
          </span>
          <span className="text-xs text-muted">{locale === "zh" ? "按设置策略" : "per settings"}</span>
        </button>
        {footerNote ? <p className="mt-2 text-xs text-muted">{footerNote}</p> : null}
      </div>
    </div>
  );
}

export function BooksListColumn(props: BooksListColumnProps): JSX.Element {
  const {
    locale,
    activeId,
    activeEditionId,
    manualAdd,
    onSelect,
    onSelectEdition,
    onStartManualAdd,
    onShelfChanged,
    onEditionShelfAdded,
    onItemUpdated,
    onRemoved,
    onMessage,
    onAcquireNotice
  } = props;
  const [query, setQuery] = useState("");
  const [editions, setEditions] = useState<BookEditionHit[]>([]);
  const [extraLinks, setExtraLinks] = useState<BookSearchHit[]>([]);
  const [showShelf, setShowShelf] = useState(true);
  const [searching, setSearching] = useState(false);
  const [acquiringKey, setAcquiringKey] = useState<string | null>(null);
  const [items, setItems] = useState<BookShelfItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<BookStatus | "all">("all");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState(false);
  const [cachedById, setCachedById] = useState<Record<number, ShelfCachedState>>({});
  const [kindleBusyId, setKindleBusyId] = useState<number | null>(null);
  const [restoreBusyId, setRestoreBusyId] = useState<number | null>(null);

  const allVisibleSelected = items.length > 0 && items.every((row) => selectedIds.has(row.id));

  const { startAcquire, acquireDialog } = useBookAcquireConfirm({
    locale,
    onAcquireNotice,
    onMessage,
    onSuccess: (result, request) => {
      if (result.shelf_item) {
        const row = result.shelf_item;
        setItems((prev) => {
          const idx = prev.findIndex((item) => item.id === row.id);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = row;
            return next;
          }
          return prev;
        });
        void probeShelfCachedFiles(row.id).then((state) => {
          setCachedById((prev) => ({ ...prev, [row.id]: state }));
        });
        onItemUpdated?.(row);
        if (request.shelf_item_id) {
          onShelfChanged();
        } else {
          onEditionShelfAdded(row);
        }
      } else if (request.add_to_shelf) {
        onShelfChanged();
      }
    }
  });

  useEffect(() => {
    let cancelled = false;
    if (items.length === 0) {
      setCachedById({});
      return;
    }
    void Promise.all(
      items.map(async (item) => {
        const state = await probeShelfCachedFiles(item.id);
        return { id: item.id, state };
      })
    ).then((rows) => {
      if (cancelled) return;
      const next: Record<number, ShelfCachedState> = {};
      for (const row of rows) {
        next[row.id] = row.state;
      }
      setCachedById(next);
    });
    return () => {
      cancelled = true;
    };
  }, [items]);

  const loadShelf = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listBookShelf(statusFilter === "all" ? undefined : statusFilter);
      setItems(resp.items);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, [onMessage, statusFilter]);

  useEffect(() => {
    void loadShelf();
  }, [loadShelf]);

  async function runSearch(): Promise<void> {
    const q = query.trim();
    if (!q) {
      setEditions([]);
      setExtraLinks([]);
      setShowShelf(true);
      return;
    }
    setSearching(true);
    setShowShelf(false);
    try {
      const resp = await searchBooks({ query: q });
      setEditions(resp.editions);
      setExtraLinks(resp.links);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "search failed");
      setShowShelf(true);
    } finally {
      setSearching(false);
    }
  }

  async function acquireEdition(edition: BookEditionHit, addToShelf: boolean): Promise<void> {
    const key = `${edition.edition_id}:${addToShelf ? "shelf" : "dl"}`;
    if (acquiringKey) return;
    setAcquiringKey(key);
    try {
      await startAcquire(editionAcquireRequest(edition, null, addToShelf));
    } finally {
      setAcquiringKey(null);
    }
  }

  function handleToggleSelect(id: number): void {
    if (!selectionMode) {
      setSelectionMode(true);
      setSelectedIds(new Set([id]));
      return;
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      if (next.size === 0) {
        setSelectionMode(false);
        setBatchDeleteConfirm(false);
      }
      return next;
    });
  }

  function toggleSelectAllVisible(): void {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
      setBatchDeleteConfirm(false);
      return;
    }
    setSelectionMode(true);
    setSelectedIds(new Set(items.map((row) => row.id)));
  }

  function exitSelectionMode(): void {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setBatchDeleteConfirm(false);
  }

  async function handleToggleFavorite(item: BookShelfItem): Promise<void> {
    const starred = (item.importance ?? 0) >= 1;
    try {
      const updated = await updateBookShelfItem(item.id, { importance: starred ? null : 4 });
      setItems((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      onItemUpdated?.(updated);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "favorite failed");
    }
  }

  async function handleSendKindle(item: BookShelfItem): Promise<void> {
    setKindleBusyId(item.id);
    try {
      const result = await sendBookShelfToKindle(item.id);
      if (result.shelf_item) {
        setItems((prev) => prev.map((row) => (row.id === result.shelf_item!.id ? result.shelf_item! : row)));
        onItemUpdated?.(result.shelf_item);
      }
      onAcquireNotice(buildKindleSendNotice(locale, result));
      if (result.kindle_status !== "sent" && !result.kindle_sent) {
        onMessage(buildKindleSendNotice(locale, result).message);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "kindle failed";
      onAcquireNotice({ kind: "error", message });
      onMessage(message);
    } finally {
      setKindleBusyId(null);
    }
  }

  async function handleRestoreDownload(item: BookShelfItem): Promise<void> {
    setRestoreBusyId(item.id);
    try {
      await startAcquire(shelfRestoreRequest(item));
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "restore failed");
    } finally {
      setRestoreBusyId(null);
    }
  }

  async function handleDeleteItem(id: number): Promise<void> {
    try {
      await deleteBookShelfItem(id);
      setItems((prev) => prev.filter((row) => row.id !== id));
      onRemoved?.(id);
      onShelfChanged();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "delete failed");
    }
  }

  async function handleBatchFavorite(): Promise<void> {
    const selected = items.filter((row) => selectedIds.has(row.id));
    if (selected.length === 0) return;
    const allStarred = selected.every((row) => (row.importance ?? 0) >= 1);
    const target = allStarred ? null : 4;
    try {
      for (const row of selected) {
        const isStarred = (row.importance ?? 0) >= 1;
        if (target !== null && isStarred) continue;
        if (target === null && !isStarred) continue;
        const updated = await updateBookShelfItem(row.id, { importance: target });
        setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
        if (activeId === updated.id) onItemUpdated?.(updated);
      }
      onMessage(
        locale === "zh"
          ? target
            ? `已收藏 ${selected.length} 本`
            : `已取消收藏 ${selected.length} 本`
          : target
            ? `Favorited ${selected.length} books`
            : `Unfavorited ${selected.length} books`
      );
      exitSelectionMode();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "favorite failed");
    }
  }

  async function handleBatchDelete(): Promise<void> {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    try {
      for (const id of ids) {
        await deleteBookShelfItem(id);
        onRemoved?.(id);
      }
      setItems((prev) => prev.filter((row) => !selectedIds.has(row.id)));
      onShelfChanged();
      exitSelectionMode();
      onMessage(locale === "zh" ? `已移除 ${ids.length} 本` : `Removed ${ids.length} books`);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "delete failed");
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {acquireDialog}
      <div className="mb-3 border-b border-border pb-3">
        <div className="on1y-glass-trigger flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5">
            <Search className="h-4 w-4 shrink-0 text-muted" />
            <input
              value={query}
              onChange={(e) => {
                const next = e.target.value;
                setQuery(next);
                if (!next.trim()) {
                  setShowShelf(true);
                  setEditions([]);
                  setExtraLinks([]);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void runSearch();
              }}
              placeholder={locale === "zh" ? "搜索图书，按 Enter…" : "Search books, press Enter…"}
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
            {searching ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted" /> : null}
        </div>
      </div>

      {editions.length > 0 ? (
        <div className="mb-3 min-h-0 flex-1 space-y-2 overflow-y-auto">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">
            {locale === "zh"
              ? `搜索结果 (${editions.length})`
              : `Results (${editions.length})`}
          </p>
          {editions.map((edition) => {
            const plusKey = `${edition.edition_id}:shelf`;
            return (
            <div
              key={edition.edition_id}
              className={`w-full rounded-md border p-2.5 transition-colors ${
                activeEditionId === edition.edition_id && !manualAdd && activeId == null
                  ? "border-accent/50 bg-accent/5"
                  : "border-border bg-surface hover:bg-soft"
              }`}
            >
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => onSelectEdition(edition)}
                  className="flex min-w-0 flex-1 gap-3 text-left"
                >
                  {edition.cover_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={bookCoverSrc(edition.cover_url)}
                      alt=""
                      className="h-20 w-14 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <div className="flex h-20 w-14 shrink-0 items-center justify-center rounded bg-panel text-muted">
                      <BookOpen className="h-5 w-5" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="font-medium leading-snug text-foreground">{edition.title}</p>
                    {editionMetaLine(edition) ? (
                      <p className="mt-1 text-xs leading-relaxed text-muted">{editionMetaLine(edition)}</p>
                    ) : null}
                    {edition.rating != null ? (
                      <p className="mt-1.5 text-xs text-amber-700">★ {ratingLabel(edition)}</p>
                    ) : null}
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => void acquireEdition(edition, true)}
                  disabled={acquiringKey === plusKey}
                  title={
                    locale === "zh"
                      ? "加入书架并下载（按设置策略）"
                      : "Add to shelf and download (per settings)"
                  }
                  className="flex h-8 w-8 shrink-0 items-center justify-center self-start rounded-md border border-border text-muted hover:bg-panel hover:text-foreground disabled:opacity-50"
                >
                  {acquiringKey === plusKey ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Plus className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>
          );
          })}
          {extraLinks.length > 0 ? (
            <div className="border-t border-border pt-2">
              {extraLinks.map((hit) => (
                <a
                  key={`${hit.source_id}-${hit.url}`}
                  href={hit.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between rounded-md px-2 py-1.5 text-xs text-muted hover:bg-soft hover:text-foreground"
                >
                  <span>
                    {locale === "zh"
                      ? `在 ${hit.source_name} 继续搜索`
                      : `Search more on ${hit.source_name}`}
                  </span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {showShelf ? (
      <div className="flex min-h-0 flex-1 flex-col">
      <div className={`min-h-0 ${editions.length > 0 ? "shrink-0 border-t border-border pt-3" : ""}`}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">
            {locale === "zh" ? "我的书架" : "My shelf"}
          </p>
          <button
            type="button"
            onClick={onStartManualAdd}
            className={`inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-soft ${
              manualAdd ? "bg-soft" : ""
            }`}
          >
            <Plus className="h-3.5 w-3.5" />
            {locale === "zh" ? "手动添加" : "Add manually"}
          </button>
        </div>
        <div className="mb-2 flex flex-wrap gap-1">
          {(["all", ...STATUS_OPTIONS] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setStatusFilter(value)}
              className={`rounded-md px-2 py-1 text-xs ${
                statusFilter === value
                  ? "bg-soft text-foreground"
                  : "text-muted hover:bg-soft hover:text-foreground"
              }`}
            >
              {value === "all"
                ? locale === "zh"
                  ? "全部"
                  : "All"
                : statusLabel(locale, value)}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {selectionMode ? (
          <div className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-border bg-panel px-2 py-1.5">
            <div className="flex min-w-0 items-center gap-2">
              <button
                type="button"
                onClick={toggleSelectAllVisible}
                title={locale === "zh" ? "全选" : "Select all"}
                aria-label={locale === "zh" ? "全选" : "Select all"}
                aria-pressed={allVisibleSelected}
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition-colors ${
                  allVisibleSelected
                    ? "border-inverse bg-inverse text-inverse-foreground"
                    : "border-border bg-surface text-muted hover:border-muted"
                }`}
              >
                {allVisibleSelected ? (
                  <CheckSquare className="h-4 w-4" />
                ) : (
                  <Square className="h-4 w-4" />
                )}
              </button>
              <span className="truncate text-xs font-medium text-foreground">
                {locale === "zh"
                  ? `已选 ${selectedIds.size} 本`
                  : `${selectedIds.size} selected`}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              <button
                type="button"
                onClick={() => void handleBatchFavorite()}
                disabled={selectedIds.size === 0}
                title={locale === "zh" ? "收藏" : "Favorite"}
                aria-label={locale === "zh" ? "收藏" : "Favorite"}
                className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground disabled:opacity-40"
              >
                <Star className="h-4 w-4" />
              </button>
              {batchDeleteConfirm ? (
                <button
                  type="button"
                  onClick={() => void handleBatchDelete()}
                  disabled={selectedIds.size === 0}
                  title={locale === "zh" ? "确认删除" : "Confirm delete"}
                  aria-label={locale === "zh" ? "确认删除" : "Confirm delete"}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-red-600 hover:bg-red-50 disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setBatchDeleteConfirm(true)}
                  disabled={selectedIds.size === 0}
                  title={locale === "zh" ? "删除" : "Delete"}
                  aria-label={locale === "zh" ? "删除" : "Delete"}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-red-500 disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
              <button
                type="button"
                onClick={exitSelectionMode}
                title={locale === "zh" ? "退出批量" : "Exit batch"}
                aria-label={locale === "zh" ? "退出批量" : "Exit batch"}
                className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        ) : null}
        {loading ? (
          <p className="text-sm text-muted">{locale === "zh" ? "加载中…" : "Loading…"}</p>
        ) : items.length === 0 ? (
          <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
            {locale === "zh" ? "书架为空" : "Shelf is empty"}
          </div>
        ) : (
          items.map((item) => {
            const cached = cachedById[item.id];
            const files = cached?.files ?? [];
            const cachedReady = cached?.ready ?? false;
            const primaryPath = files[0]?.path ?? null;
            return (
              <BookShelfCard
                key={item.id}
                item={item}
                locale={locale}
                active={activeId === item.id && !manualAdd}
                selected={selectedIds.has(item.id)}
                selectionMode={selectionMode}
                hasLocalFile={files.length > 0}
                cachedReady={cachedReady}
                primaryPath={primaryPath}
                kindleBusy={kindleBusyId === item.id}
                restoreBusy={restoreBusyId === item.id}
                canRestore={canRestoreShelf(item)}
                onSelect={() => onSelect(item)}
                onToggleSelected={() => handleToggleSelect(item.id)}
                onToggleFavorite={() => void handleToggleFavorite(item)}
                onOpenLocal={() =>
                  void openLocalPath(primaryPath!).catch((error) =>
                    onMessage(error instanceof Error ? error.message : "open failed")
                  )
                }
                onSendKindle={() => void handleSendKindle(item)}
                onRestoreDownload={() => void handleRestoreDownload(item)}
                onDelete={() => void handleDeleteItem(item.id)}
              />
            );
          })
        )}
      </div>
      </div>
      ) : null}
    </div>
  );
}

export function BooksDetailColumn(props: BooksDetailColumnProps): JSX.Element {
  const {
    locale,
    item,
    edition,
    manualAdd,
    onAcquireNotice,
    onSaved,
    onDeleted,
    onCancelManual,
    onMessage,
    onSelectShelfItem,
    onSelectKnowledgeItem
  } = props;
  const [shelfItem, setShelfItem] = useState<BookShelfItem | null>(null);
  const [shelfLoading, setShelfLoading] = useState(false);
  const [detail, setDetail] = useState<BookWorkDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [status, setStatus] = useState<BookStatus>("reading");
  const [notes, setNotes] = useState("");
  const [links, setLinks] = useState<{ label: string; url: string }[]>([{ label: "", url: "" }]);
  const [saving, setSaving] = useState(false);
  const [detailAcquiring, setDetailAcquiring] = useState(false);
  const [zlibEnabled, setZlibEnabled] = useState(true);
  const [annasEnabled, setAnnasEnabled] = useState(true);
  const [zlibBaseUrl, setZlibBaseUrl] = useState(BOOK_ZLIB_BASE);

  const { startAcquire, acquireDialog } = useBookAcquireConfirm({
    locale,
    onAcquireNotice,
    onMessage,
    onSuccess: (result) => {
      if (result.shelf_item) {
        onSaved(result.shelf_item);
      }
    }
  });

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchBookSources(), fetchBookSettings()])
      .then(([sourcesFile, bookSettings]) => {
        if (cancelled) return;
        const toggles = readBuiltinToggles(sourcesFile);
        setZlibEnabled(toggles.zlibEnabled);
        setAnnasEnabled(toggles.annasEnabled);
        setZlibBaseUrl(bookSettings.zlib_base_url || BOOK_ZLIB_BASE);
      })
      .catch(() => {
        /* keep defaults */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (manualAdd || edition || !item) {
      setShelfItem(null);
      return;
    }
    let cancelled = false;
    setShelfLoading(true);
    setShelfItem(item);
    void fetchBookShelfItem(item.id)
      .then((data) => {
        if (!cancelled) setShelfItem(data);
      })
      .catch(() => {
        if (!cancelled) setShelfItem(item);
      })
      .finally(() => {
        if (!cancelled) setShelfLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item?.id, edition, manualAdd]);

  useEffect(() => {
    if (!item || manualAdd || edition) return;
    setShelfItem((prev) => {
      if (prev?.id !== item.id) return prev;
      if (!item.updated_at || !prev.updated_at || item.updated_at >= prev.updated_at) {
        return { ...prev, ...item };
      }
      return prev;
    });
  }, [item, edition, manualAdd]);

  const sourceLinkToggles = { zlibEnabled, annasEnabled };
  const sourceLinks =
    detail?.source_links && detail.source_links.length > 0
      ? detail.source_links
      : detail != null
        ? buildEditionSourceLinks(
            {
              title: detail.title,
              doubanUrl: detail.url,
              author: detail.author,
              translator: detail.translator
            },
            zlibBaseUrl,
            sourceLinkToggles
          )
        : edition != null
          ? buildEditionSourceLinks(
              {
                title: edition.title,
                doubanUrl: edition.url,
                author: edition.author,
                translator: edition.translator
              },
              zlibBaseUrl,
              sourceLinkToggles
            )
          : [];

  async function acquireFromDetail(): Promise<void> {
    if (!edition || detailAcquiring) return;
    setDetailAcquiring(true);
    try {
      await startAcquire(editionAcquireRequest(edition, detail, false));
    } finally {
      setDetailAcquiring(false);
    }
  }

  useEffect(() => {
    if (manualAdd) {
      setDetail(null);
      return;
    }
    if (item) {
      return;
    }
    if (!edition) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void fetchBookDetail(edition.url)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((error) => {
        if (!cancelled) {
          onMessage(error instanceof Error ? error.message : "load detail failed");
          setDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [edition, item, manualAdd, onMessage]);

  useEffect(() => {
    if (manualAdd) {
      setTitle("");
      setAuthor("");
      setStatus("reading");
      setNotes("");
      setLinks([{ label: "", url: "" }]);
      return;
    }
    if (!item) return;
    setTitle(item.title);
    setAuthor(item.author || "");
    setStatus(item.status);
    setNotes(item.notes || "");
    setLinks(item.links.length > 0 ? item.links.map((l) => ({ ...l })) : [{ label: "", url: "" }]);
  }, [item, manualAdd]);

  if (!manualAdd && item) {
    return (
      <>
        {acquireDialog}
        <div className="h-full overflow-hidden p-4">
          {shelfLoading || !shelfItem ? (
            <p className="text-sm text-muted">{locale === "zh" ? "加载中…" : "Loading…"}</p>
          ) : (
            <BookShelfDetail
              locale={locale}
              item={shelfItem}
              onSaved={onSaved}
              onSelectShelfItem={onSelectShelfItem}
              onSelectKnowledgeItem={onSelectKnowledgeItem}
              onMessage={onMessage}
            />
          )}
        </div>
      </>
    );
  }

  if (!manualAdd && !item && edition) {
    return (
      <>
        {acquireDialog}
        <div className="h-full overflow-y-auto p-4">
        {detailLoading ? (
          <p className="text-sm text-muted">{locale === "zh" ? "加载详情…" : "Loading…"}</p>
        ) : detail ? (
          <DoubanDetailBody
            locale={locale}
            detail={detail}
            sourceLinks={sourceLinks}
            acquiring={detailAcquiring}
            onDownload={() => void acquireFromDetail()}
            footerNote={
              locale === "zh"
                ? "下载前会展示 Z-Library 最受欢迎的前 3 条供选择；格式限制见 设置 → 图书。"
                : "Top 3 Z-Library results by popularity before download; format filter in Settings → Books."
            }
          />
        ) : (
          <p className="text-sm text-muted">{locale === "zh" ? "无法加载详情" : "Detail unavailable"}</p>
        )}
        </div>
      </>
    );
  }

  if (!manualAdd && !item) {
    return (
      <>
        {acquireDialog}
        <div className="flex h-full items-center justify-center p-6 text-sm text-muted">
          {locale === "zh" ? "选择一本书查看详情" : "Select a book"}
        </div>
      </>
    );
  }

  async function handleSave(): Promise<void> {
    const cleanLinks = links
      .map((l) => ({ label: l.label.trim(), url: l.url.trim() }))
      .filter((l) => l.label && l.url);
    if (!title.trim() || cleanLinks.length === 0) {
      onMessage(locale === "zh" ? "请填写书名和至少一条链接" : "Title and at least one link required");
      return;
    }
    setSaving(true);
    try {
      const created = await createBookShelfItem({
        title: title.trim(),
        author: author.trim() || null,
        status,
        links: cleanLinks,
        notes: notes.trim() || null
      });
      onSaved(created);
      onMessage(locale === "zh" ? "已保存" : "Saved");
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {acquireDialog}
      <div className="h-full overflow-y-auto p-4">
      <h2 className="mb-4 text-base font-semibold">
        {locale === "zh" ? "手动添加" : "Add book"}
      </h2>
      <div className="space-y-3">
        <label className="block text-xs text-muted">
          {locale === "zh" ? "书名" : "Title"}
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-muted">
          {locale === "zh" ? "作者" : "Author"}
          <input
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-muted">
          {locale === "zh" ? "状态" : "Status"}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as BookStatus)}
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {statusLabel(locale, opt)}
              </option>
            ))}
          </select>
        </label>
        <div>
          <p className="mb-1 text-xs text-muted">{locale === "zh" ? "外链" : "Links"}</p>
          <div className="space-y-2">
            {links.map((link, index) => (
              <div key={index} className="flex gap-2">
                <input
                  value={link.label}
                  onChange={(e) => {
                    const next = [...links];
                    next[index] = { ...next[index], label: e.target.value };
                    setLinks(next);
                  }}
                  placeholder={locale === "zh" ? "来源名称" : "Label"}
                  className="w-28 shrink-0 rounded-md border border-border bg-surface px-2 py-1 text-xs"
                />
                <input
                  value={link.url}
                  onChange={(e) => {
                    const next = [...links];
                    next[index] = { ...next[index], url: e.target.value };
                    setLinks(next);
                  }}
                  placeholder="https://"
                  className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-xs"
                />
              </div>
            ))}
            <button
              type="button"
              onClick={() => setLinks((prev) => [...prev, { label: "", url: "" }])}
              className="text-xs text-muted hover:text-foreground"
            >
              + {locale === "zh" ? "添加链接" : "Add link"}
            </button>
          </div>
          {links.some((l) => l.url.trim()) ? (
            <div className="mt-3 rounded-md border border-border bg-panel p-3">
              <p className="mb-2 text-xs font-medium text-muted">
                {locale === "zh" ? "快速打开" : "Quick open"}
              </p>
              <div className="space-y-1.5">
                {links
                  .filter((l) => l.url.trim())
                  .map((link) => (
                    <a
                      key={`${link.label}-${link.url}`}
                      href={link.url.trim()}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-soft"
                    >
                      <span>{link.label.trim() || link.url.trim()}</span>
                      <ExternalLink className="h-3.5 w-3.5 text-muted" />
                    </a>
                  ))}
              </div>
            </div>
          ) : null}
        </div>
        <label className="block text-xs text-muted">
          {locale === "zh" ? "备注" : "Notes"}
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={4}
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
          />
        </label>
        <div className="flex flex-wrap gap-2 pt-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-50"
          >
            {locale === "zh" ? "保存" : "Save"}
          </button>
          <button
            type="button"
            onClick={onCancelManual}
            className="rounded-md border border-border px-3 py-1.5 text-sm"
          >
            {locale === "zh" ? "取消" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
    </>
  );
}

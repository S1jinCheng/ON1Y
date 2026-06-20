"use client";

import {
  BookOpen,
  Download,
  ExternalLink,
  Loader2,
  Plus,
  Search,
  Trash2
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { BookShelfDetail } from "@/components/book-shelf-detail";
import {
  type BookAcquireRequest,
  useBookAcquireConfirm
} from "@/components/book-acquire-confirm-dialog";
import { type BookAcquireNotice } from "@/components/book-acquire-notice";

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
  updateBookShelfItem
} from "@/lib/api";
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
    if (link.label === "豆瓣" || /douban\.com/i.test(link.url)) {
      return link.url;
    }
  }
  return null;
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
              <img
                src={detail.cover_url}
                alt=""
                className="h-36 w-24 rounded object-cover"
                referrerPolicy="no-referrer"
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

  const { startAcquire, acquireDialog } = useBookAcquireConfirm({
    locale,
    onAcquireNotice,
    onMessage,
    onSuccess: (result, request) => {
      if (result.shelf_item) {
        onEditionShelfAdded(result.shelf_item);
      } else if (request.add_to_shelf) {
        onShelfChanged();
      }
    }
  });

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
                    <img
                      src={edition.cover_url}
                      alt=""
                      className="h-20 w-14 shrink-0 rounded object-cover"
                      referrerPolicy="no-referrer"
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
        {loading ? (
          <p className="text-sm text-muted">{locale === "zh" ? "加载中…" : "Loading…"}</p>
        ) : items.length === 0 ? (
          <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
            {locale === "zh" ? "书架为空" : "Shelf is empty"}
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item)}
              className={`w-full rounded-md border p-2.5 text-left text-sm transition-colors ${
                activeId === item.id && !manualAdd
                  ? "border-accent/50 bg-accent/5"
                  : "border-border bg-surface hover:bg-soft"
              }`}
            >
              <div className="flex items-start gap-3">
                {item.cover_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={bookCoverSrc(item.cover_url)}
                    alt=""
                    className="h-[72px] w-[52px] shrink-0 rounded object-cover"
                  />
                ) : (
                  <div className="flex h-[72px] w-[52px] shrink-0 items-center justify-center rounded bg-panel text-muted">
                    <BookOpen className="h-5 w-5" />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-medium leading-snug text-foreground line-clamp-2">{item.title}</p>
                  <p className="mt-0.5 text-xs text-muted line-clamp-1">
                    {[item.author, item.translator].filter(Boolean).join(" / ")}
                  </p>
                  {item.summary ? (
                    <p className="mt-1 text-xs leading-relaxed text-muted line-clamp-2">{item.summary}</p>
                  ) : null}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className="rounded bg-soft px-1.5 py-0.5 text-[10px] text-muted">
                      {statusLabel(locale, item.status)}
                    </span>
                    {item.cached_format ? (
                      <span className="rounded bg-soft px-1.5 py-0.5 text-[10px] text-muted">
                        {item.cached_format.toUpperCase()}
                      </span>
                    ) : null}
                    {(item.tags ?? []).slice(0, 2).map((tag) => (
                      <span key={tag} className="rounded bg-soft px-1.5 py-0.5 text-[10px] text-muted">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </button>
          ))
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
    onMessage
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
              onDeleted={onDeleted}
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

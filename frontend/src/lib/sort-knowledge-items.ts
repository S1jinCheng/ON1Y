import type { KnowledgeItem, Locale } from "@/lib/types";

export type SortMode =
  | "ingested_desc"
  | "ingested_asc"
  | "published_desc"
  | "published_asc"
  | "title_asc"
  | "title_desc"
  | "hot_rank_asc"
  | "relevance";

export const SORT_MODES: SortMode[] = [
  "ingested_desc",
  "ingested_asc",
  "published_desc",
  "published_asc",
  "title_asc",
  "title_desc",
  "hot_rank_asc",
  "relevance"
];

export const DEFAULT_SORT_MODE: SortMode = "published_desc";

const STORAGE_KEY = "on1y-knowledge-sort-mode";

export function loadSortMode(): SortMode {
  if (typeof window === "undefined") {
    return DEFAULT_SORT_MODE;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === "author_asc" || raw === "author_desc") {
    return DEFAULT_SORT_MODE;
  }
  if (raw && SORT_MODES.includes(raw as SortMode)) {
    return raw as SortMode;
  }
  return DEFAULT_SORT_MODE;
}

export function persistSortMode(mode: SortMode): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, mode);
}

function parseTime(iso: string | null | undefined): number {
  if (!iso) {
    return 0;
  }
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

function publishedTime(item: KnowledgeItem): number {
  return parseTime(item.published_at) || parseTime(item.ingested_at);
}

function collator(locale: Locale): Intl.Collator {
  return new Intl.Collator(locale === "zh" ? "zh-CN" : "en", {
    sensitivity: "base",
    numeric: true
  });
}

export function sortKnowledgeItems(
  items: KnowledgeItem[],
  mode: SortMode,
  locale: Locale,
  options?: { hasSearch?: boolean }
): KnowledgeItem[] {
  const sorted = [...items];
  const cmp = collator(locale);
  const effective =
    mode === "relevance" && !options?.hasSearch ? DEFAULT_SORT_MODE : mode;

  switch (effective) {
    case "relevance":
      sorted.sort((a, b) => (a.search_rank ?? 0) - (b.search_rank ?? 0));
      break;
    case "ingested_desc":
      sorted.sort((a, b) => parseTime(b.ingested_at) - parseTime(a.ingested_at));
      break;
    case "ingested_asc":
      sorted.sort((a, b) => parseTime(a.ingested_at) - parseTime(b.ingested_at));
      break;
    case "published_desc":
      sorted.sort((a, b) => publishedTime(b) - publishedTime(a));
      break;
    case "published_asc":
      sorted.sort((a, b) => publishedTime(a) - publishedTime(b));
      break;
    case "title_asc":
      sorted.sort((a, b) =>
        cmp.compare((a.title || a.url || "").trim(), (b.title || b.url || "").trim())
      );
      break;
    case "title_desc":
      sorted.sort((a, b) =>
        cmp.compare((b.title || b.url || "").trim(), (a.title || a.url || "").trim())
      );
      break;
    case "hot_rank_asc":
      sorted.sort((a, b) => {
        const ra = a.hot_rank ?? Number.MAX_SAFE_INTEGER;
        const rb = b.hot_rank ?? Number.MAX_SAFE_INTEGER;
        if (ra !== rb) {
          return ra - rb;
        }
        return publishedTime(b) - publishedTime(a);
      });
      break;
    default:
      break;
  }
  return sorted;
}

export function sortOptionsForUi(
  locale: Locale,
  hasSearch: boolean,
  collection: "feed" | "favorites" | "trash" | "hotlist" | "notes" | "chats" = "feed"
): Array<{ value: SortMode; label: string }> {
  const zh = locale === "zh";
  const base: Array<{ value: SortMode; label: string }> = [
    { value: "published_desc", label: zh ? "发布时间 ↓" : "Published ↓" },
    { value: "published_asc", label: zh ? "发布时间 ↑" : "Published ↑" },
    { value: "ingested_desc", label: zh ? "入库时间 ↓" : "Ingested ↓" },
    { value: "ingested_asc", label: zh ? "入库时间 ↑" : "Ingested ↑" },
    { value: "title_asc", label: zh ? "标题 A→Z" : "Title A→Z" },
    { value: "title_desc", label: zh ? "标题 Z→A" : "Title Z→A" },
    { value: "hot_rank_asc", label: zh ? "热榜排名" : "Hot rank" }
  ];
  if (collection === "hotlist") {
    if (hasSearch) {
      return [{ value: "relevance", label: zh ? "搜索相关度" : "Relevance" }];
    }
    return [];
  }
  if (hasSearch) {
    return [{ value: "relevance", label: zh ? "搜索相关度" : "Relevance" }, ...base];
  }
  return base;
}

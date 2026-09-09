"use client";

import * as Select from "@radix-ui/react-select";
import {
  BarChart3,
  BookOpen,
  CheckSquare,
  ChevronDown,
  Clock,
  ExternalLink,
  Flame,
  Forward,
  FileText,
  Heart,
  Inbox,
  Network,
  MessageCircle,
  NotebookPen,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Star,
  Check,
  Trash2,
  X
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { ColdStartFloatingPanel } from "@/components/cold-start-floating-panel";
import { AppUpdateBanner } from "@/components/app-update-banner";
import { BookAcquireNoticeBar, type BookAcquireNotice } from "@/components/book-acquire-notice";
import { PipelineAlertsBanner } from "@/components/pipeline-alerts-banner";
import { FirstRunGuide } from "@/components/first-run-guide";
import { FeedItemCard } from "@/components/feed-item-card";
import { ThemeMovePopover } from "@/components/theme-move-popover";
import { NotesPanel } from "@/components/notes-panel";
import { BooksDetailColumn, BooksListColumn } from "@/components/books-panel";
import { PapersDetailColumn, PapersListColumn } from "@/components/papers-panel";
import { invalidateNotePreviewCache } from "@/components/note-hover-preview";
import { ConversationTranscriptPanel } from "@/components/conversation-transcript-panel";
import { OriginalTextPanel } from "@/components/original-text-panel";
import { ContentTypeIndicator } from "@/components/content-type-indicator";
import { RelatedItemsSection } from "@/components/related-items-section";
import { AccountMenu } from "@/components/account-menu";
import { TagChipEditor } from "@/components/tag-chip-editor";
import { EveningDigestButton } from "@/components/evening-digest-button";
import { FeedDatePicker } from "@/components/feed-date-calendar";
import { ThemeSidebar } from "@/components/theme-sidebar";
import { CreatorSidebar } from "@/components/creator-sidebar";
import {
  absorbThemeFromOther,
  createTheme,
  batchDeleteKnowledgeItems,
  deleteKnowledgeItem,
  deleteTheme,
  reorderThemes,
  updateTheme,
  runHotlistSync,
  getCollectionCounts,
  getCookieStatuses,
  getCreators,
  getFullSyncStatus,
  runFullSync,
  type FullSyncStatus,
  economistEpubDownloadUrl,
  fetchBookShelfItem,
  fetchPaper,
  getEconomistWeeks,
  getKnowledgeItems,
  getStatsOverview,
  type EconomistWeekOption,
  type HotlistSource,
  getReaderContent,
  getItemRelations,
  getRelatedItems,
  createItemRelation,
  deleteItemRelation,
  markItemRead,
  patchItemRead,
  postRelatedLessRelevant,
  getTaxonomy,
  moveItemTheme,
  patchItemClassification,
  patchItemImportance,
  saveItemNote,
  restoreKnowledgeItem,
  toggleItemFavorite,
  translateItemTranscript,
  uploadDocument
} from "@/lib/api";
import { handleExternalLinkClick } from "@/lib/open-external";
import { platformLabel } from "@/lib/platform-label";
import { formatPublishedAt } from "@/lib/format-published-at";
import { t, type UiKey } from "@/lib/i18n";
import {
  type CreatorRow,
  type DynamicTagRow,
  type KnowledgeItem,
  type ReaderContent,
  type ThemeRow
} from "@/lib/types";
import type { BookEditionHit, BookShelfItem } from "@/lib/book-types";
import type { PaperItem } from "@/lib/paper-types";
import { sortKnowledgeItems, sortOptionsForUi } from "@/lib/sort-knowledge-items";
import { getUserProfile, patchUserProfile } from "@/lib/api";
import { loadStoredLocale, persistStoredLocale } from "@/lib/locale-preference";
import {
  REQUEST_INITIAL_SYNC_EVENT,
  SETTINGS_CLOSED_EVENT,
  SHOW_FIRST_RUN_GUIDE_EVENT
} from "@/lib/open-settings";
import { GLASS_MUTED, GLASS_PANEL, glassNavClass } from "@/lib/nav-glass";
import { hasSyncCookies } from "@/lib/sync-cookies";
import { todayIsoDate } from "@/lib/today-iso-date";
import {
  ALL_FILTER,
  hydrateKnowledgeSortMode,
  type KnowledgeCollection,
  useKnowledgeFilterStore
} from "@/store/knowledge-store";
import type { Locale } from "@/lib/i18n";

/** Match backend `SHORT_CONTENT_DISTILL_MAX_CHARS`. */
const SHORT_CONTENT_SUMMARY_MAX_CHARS = 150;

type LinkedRelation = {
  relationId: number;
  relationType: string;
  note: string | null;
  item: KnowledgeItem;
};

function filterValue(value: string): string | undefined {
  return value === ALL_FILTER || value === "" ? undefined : value;
}

function FilterSelect(props: {
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ label: string; value: string }>;
}): JSX.Element {
  const active = props.value !== ALL_FILTER && props.value !== "";
  return (
    <Select.Root value={props.value || ALL_FILTER} onValueChange={props.onChange}>
      <Select.Trigger
        className={`inline-flex h-9 min-w-[7rem] items-center justify-between gap-2 rounded-md px-3 text-sm outline-none transition-colors ${
          active ? "on1y-glass-trigger-active" : "on1y-glass-trigger"
        }`}
      >
        <Select.Value placeholder={props.placeholder} />
        <Select.Icon>
          <ChevronDown className={`h-4 w-4 ${active ? GLASS_MUTED : "text-muted"}`} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="on1y-glass-panel z-50 overflow-hidden rounded-md shadow-on1y">
          <Select.Viewport className="p-1">
            {props.options.map((opt) => (
              <Select.Item
                key={opt.value}
                value={opt.value}
                className="on1y-glass-menu-item cursor-pointer px-2 py-1.5 text-sm outline-none"
              >
                <Select.ItemText>{opt.label}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

function ColumnScroll(props: {
  children: React.ReactNode;
  className?: string;
  onScroll?: (event: React.UIEvent<HTMLDivElement>) => void;
  scrollRef?: React.Ref<HTMLDivElement>;
}): JSX.Element {
  return (
    <div
      ref={props.scrollRef}
      onScroll={props.onScroll}
      className={`h-full min-h-0 overflow-y-auto bg-background scrollbar-thin ${props.className ?? ""}`}
    >
      {props.children}
    </div>
  );
}

/** First paint: small batch from local DB for fast list display. */
const INITIAL_FEED_BATCH = 40;
/** Scroll pagination batch size (API max 200). */
const FEED_BATCH_SIZE = 80;
const RELATION_SEARCH_BATCH_SIZE = 200;

function resolveCover(item: {
  cover_image?: string;
  author_avatar?: string;
}): string {
  const cover = item.cover_image?.trim();
  if (cover) {
    return cover;
  }
  const legacy = item.author_avatar?.trim() ?? "";
  if (legacy && /ytimg\.com\/vi\//i.test(legacy)) {
    return legacy;
  }
  return "";
}

function resolveAuthorAvatar(authorAvatar?: string): string | undefined {
  const avatar = authorAvatar?.trim();
  if (!avatar) {
    return undefined;
  }
  if (/ytimg\.com\/vi\//i.test(avatar)) {
    return undefined;
  }
  return avatar;
}

function clipSourceLabel(source: string | null | undefined, locale: Locale): string {
  const key = (source || "").trim().toLowerCase();
  if (key === "bookmarklet") {
    return locale === "zh" ? "网页剪藏" : "Web clip";
  }
  if (key === "extension") {
    return locale === "zh" ? "浏览器扩展" : "Browser extension";
  }
  if (key === "manual") {
    return locale === "zh" ? "手动剪藏" : "Manual clip";
  }
  return locale === "zh" ? "剪藏" : "Clip";
}

function extractStrategyLabel(strategy: string | null | undefined, locale: Locale): string {
  const key = (strategy || "").trim().toLowerCase();
  if (key === "selected_text") {
    return locale === "zh" ? "选中文本" : "Selected text";
  }
  if (key === "jina") {
    return locale === "zh" ? "Jina" : "Jina";
  }
  if (key === "bs4") {
    return locale === "zh" ? "网页回退" : "HTML fallback";
  }
  return key || (locale === "zh" ? "抽取" : "Extract");
}

function formatDurationSeconds(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  const total = Math.floor(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return hours + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
  }
  return minutes + ":" + String(seconds).padStart(2, "0");
}

function formatSocialCount(value: number | null | undefined, locale: Locale): string | null {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) {
    return null;
  }
  return new Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}

function ActiveItemMeta(props: { item: KnowledgeItem; locale: Locale; ui: (key: UiKey) => string }): JSX.Element | null {
  const { item, locale, ui } = props;
  const published = formatPublishedAt(item.published_at || item.ingested_at, locale);
  const duration = item.content_type === "video" ? formatDurationSeconds(item.duration_sec) : null;
  const likes = formatSocialCount(item.like_count, locale);
  const comments = formatSocialCount(item.comment_count, locale);
  if (!published && !duration && !likes && !comments) {
    return null;
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      {published ? (
        <span className="inline-flex items-center gap-1" title={ui("publishedAt")}>
          <Clock className="h-3.5 w-3.5" aria-hidden />
          {published}
        </span>
      ) : null}
      {duration ? (
        <span className="inline-flex items-center gap-1" title={ui("videoDuration")}>
          <span aria-hidden>◷</span>
          {duration}
        </span>
      ) : null}
      {likes ? (
        <span className="inline-flex items-center gap-1" title={ui("likes")}>
          <Heart className="h-3.5 w-3.5" aria-hidden />
          {likes}
        </span>
      ) : null}
      {comments ? (
        <span className="inline-flex items-center gap-1" title={ui("comments")}>
          <MessageCircle className="h-3.5 w-3.5" aria-hidden />
          {comments}
        </span>
      ) : null}
    </div>
  );
}

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function highlightTextHtml(text: string, needle: string): string {
  const source = text || "";
  const q = needle.trim();
  if (!q) {
    return "";
  }
  const escapedNeedle = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matcher = new RegExp(escapedNeedle, "gi");
  const escapedSource = escapeHtml(source);
  return escapedSource.replace(matcher, (m) => `<mark>${m}</mark>`);
}

function withLocalSearchHighlight(item: KnowledgeItem, q: string): KnowledgeItem {
  const title = item.title || item.url || "";
  const summary = item.summary || item.search_snippet || "";
  return {
    ...item,
    search_title_html: highlightTextHtml(title, q),
    search_summary_html: highlightTextHtml(summary, q)
  };
}

type ObsidianWritebackLight = "red" | "yellow" | "green";

function resolveObsidianWritebackLight(
  linkedCount: number,
  status: string | null | undefined
): ObsidianWritebackLight {
  if (linkedCount <= 0) {
    return "red";
  }
  const key = (status || "").trim().toLowerCase();
  if (key === "applied") {
    return "green";
  }
  return "yellow";
}

function obsidianWritebackLightLabel(
  locale: Locale,
  light: ObsidianWritebackLight
): string {
  if (light === "green") {
    return locale === "zh" ? "已关联且写回成功" : "Linked and writeback success";
  }
  if (light === "yellow") {
    return locale === "zh" ? "已关联，等待写回成功" : "Linked, waiting writeback success";
  }
  return locale === "zh" ? "未关联未写回" : "Not linked and not written back";
}

function ObsidianWritebackIndicator(props: {
  locale: Locale;
  linkedCount: number;
  status: string | null | undefined;
}): JSX.Element {
  const activeLight = resolveObsidianWritebackLight(props.linkedCount, props.status);
  const title = obsidianWritebackLightLabel(props.locale, activeLight);
  const dots: Array<{ key: ObsidianWritebackLight; core: string; glow: string }> = [
    { key: "red", core: "#FF0000", glow: "#FF0000" },
    { key: "yellow", core: "#FCEE09", glow: "#FFF000" },
    { key: "green", core: "#00FF22", glow: "#00FF44" }
  ];
  return (
    <span className="inline-flex items-center gap-[7px]" title={title} role="status" aria-label={title}>
      {dots.map((dot) => (
        <span
          key={dot.key}
          className={`kindle-neon-dot ${
            activeLight === dot.key ? "kindle-neon-dot--on" : "kindle-neon-dot--off"
          }`}
          style={
            {
              "--kindle-neon-core": dot.core,
              "--kindle-neon-glow": dot.glow
            } as CSSProperties
          }
          aria-hidden
        />
      ))}
    </span>
  );
}

function AuthorAvatar(props: {
  author: string;
  authorAvatar?: string;
  unknownLabel: string;
  size?: "sm" | "md";
}): JSX.Element {
  const name = props.author.trim() || props.unknownLabel;
  const sizeClass = props.size === "md" ? "h-10 w-10 text-sm" : "h-9 w-9 text-xs";
  if (props.authorAvatar?.trim()) {
    return (
      <img
        src={props.authorAvatar}
        alt=""
        className={`${sizeClass} shrink-0 rounded-full object-cover bg-soft`}
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <div
      className={`${sizeClass} flex shrink-0 items-center justify-center rounded-full bg-soft font-medium text-muted`}
    >
      {name.slice(0, 1).toUpperCase()}
    </div>
  );
}

export default function KnowledgeWorkbench(): JSX.Element {
  const {
    locale,
    sidebarMode,
    selectedThemeId,
    selectedCreatorKey,
    selectedTagId,
    query,
    platform,
    setLocale,
    setSidebarMode,
    setTheme,
    setCreator,
    selectTheme,
    selectCreator,
    setQuery,
    setPlatform,
    collection,
    setCollection,
    sortMode,
    setSortMode
  } = useKnowledgeFilterStore();

  const isTrash = collection === "trash";
  const isFavorites = collection === "favorites";
  const isHotlist = collection === "hotlist";
  const isNotes = collection === "notes";
  const isChats = collection === "chats";
  const isBooks = collection === "books";
  const isPapers = collection === "papers";
  const isFeedBrowse = !isTrash && !isFavorites && !isHotlist && !isNotes && !isChats && !isBooks && !isPapers;
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [minImportance, setMinImportance] = useState<number | null>(null);

  const ui = (key: UiKey): string => t(locale, key);

  const [themes, setThemes] = useState<ThemeRow[]>([]);
  const [creators, setCreators] = useState<CreatorRow[]>([]);
  const [dynamicTags, setDynamicTags] = useState<DynamicTagRow[]>([]);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [active, setActive] = useState<KnowledgeItem | undefined>(undefined);
  const [reader, setReader] = useState<ReaderContent | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(false);
  const [coldStartOnboardingOpen, setColdStartOnboardingOpen] = useState(false);
  const [coldStartStatus, setColdStartStatus] = useState<FullSyncStatus | null>(null);
  const [message, setMessage] = useState<string>("");
  const [tagList, setTagList] = useState<string[]>([]);
  const [relatedItems, setRelatedItems] = useState<KnowledgeItem[]>([]);
  const [linkedRelations, setLinkedRelations] = useState<LinkedRelation[]>([]);
  const [selectedLinkedIds, setSelectedLinkedIds] = useState<Set<number>>(new Set());
  const [relationQuery, setRelationQuery] = useState("");
  const [relationSearchResults, setRelationSearchResults] = useState<KnowledgeItem[]>([]);
  const [relationSearchPool, setRelationSearchPool] = useState<KnowledgeItem[]>([]);
  const [relationSearching, setRelationSearching] = useState(false);
  const [relationPanelOpen, setRelationPanelOpen] = useState(false);
  const [selectedRelationCandidateIds, setSelectedRelationCandidateIds] = useState<Set<number>>(new Set());
  const [readerExpanded, setReaderExpanded] = useState<boolean>(false);
  const [searchTotal, setSearchTotal] = useState<number | undefined>(undefined);
  const [searchEngine, setSearchEngine] = useState<string | undefined>(undefined);
  const [itemTotal, setItemTotal] = useState<number | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);
  const feedScrollRef = useRef<HTMLDivElement | null>(null);
  const [selectionMode, setSelectionMode] = useState<boolean>(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState<boolean>(false);
  const [hotlistDate, setHotlistDate] = useState<string>(todayIsoDate);
  const [hotlistSource, setHotlistSource] = useState<HotlistSource>("zhihu");
  const [economistYear, setEconomistYear] = useState<number>(() => new Date().getFullYear());
  const [economistWeek, setEconomistWeek] = useState<number>(1);
  const [economistWeeks, setEconomistWeeks] = useState<EconomistWeekOption[]>([]);
  const isEconomistHotlist = isHotlist && hotlistSource === "economist";
  const [collectionCounts, setCollectionCounts] = useState<{
    favorites: number;
    trash: number;
    hotlist: number;
    unread: number;
    notes: number;
    chats: number;
    books: number;
    papers: number;
  }>({
    favorites: 0,
    trash: 0,
    hotlist: 0,
    unread: 0,
    notes: 0,
    chats: 0,
    books: 0,
    papers: 0
  });
  const [activeBook, setActiveBook] = useState<BookShelfItem | null>(null);
  const [activeEdition, setActiveEdition] = useState<BookEditionHit | null>(null);
  const [manualAddBook, setManualAddBook] = useState(false);
  const [bookAcquireNotice, setBookAcquireNotice] = useState<BookAcquireNotice | null>(null);
  const [booksRefreshKey, setBooksRefreshKey] = useState(0);
  const [activePaper, setActivePaper] = useState<PaperItem | null>(null);
  const [manualAddPaper, setManualAddPaper] = useState(false);
  const [papersRefreshKey, setPapersRefreshKey] = useState(0);
  const [feedDate, setFeedDate] = useState<string | null>(null);
  const [calendarMonth, setCalendarMonth] = useState<Date>(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [feedDayCounts, setFeedDayCounts] = useState<Map<string, number>>(new Map());

  const platformOptions = useMemo(
    () => [
      { label: locale === "zh" ? "所有平台" : "All platforms", value: ALL_FILTER },
      { label: locale === "zh" ? "知乎" : "Zhihu", value: "zhihu" },
      { label: locale === "zh" ? "B站" : "Bilibili", value: "bilibili" },
      { label: "YouTube", value: "youtube" },
      { label: platformLabel("twitter", locale), value: "twitter" },
      { label: platformLabel("obsidian", locale), value: "obsidian" },
      { label: platformLabel("telegram", locale), value: "telegram" },
      { label: locale === "zh" ? "其他" : "Other", value: "other" }
    ],
    [locale]
  );

  const hasSearch = Boolean(query.trim());

  const selectedCreator = useMemo(
    () =>
      selectedCreatorKey
        ? creators.find((row) => row.key === selectedCreatorKey)
        : undefined,
    [creators, selectedCreatorKey]
  );

  const sortOptions = useMemo(
    () => sortOptionsForUi(locale, hasSearch, isBooks || isPapers ? "feed" : collection),
    [locale, hasSearch, collection, isBooks, isPapers]
  );
  const importanceFilterOptions = useMemo(
    () => [
      { value: ALL_FILTER, label: ui("importanceFilterAll") },
      { value: "5", label: ui("importanceFilterExact").replace("{n}", "5") },
      { value: "4", label: ui("importanceFilterStars").replace("{n}", "4") },
      { value: "3", label: ui("importanceFilterStars").replace("{n}", "3") },
      { value: "2", label: ui("importanceFilterStars").replace("{n}", "2") },
      { value: "1", label: ui("importanceFilterStars").replace("{n}", "1") }
    ],
    [locale]
  );

  const displayItems = useMemo(
    () =>
      isHotlist
        ? items
        : sortKnowledgeItems(items, sortMode, locale, { hasSearch }),
    [items, sortMode, locale, hasSearch, isHotlist]
  );
  const linkedRawIdSet = useMemo(
    () => new Set(linkedRelations.map((row) => row.item.raw_id)),
    [linkedRelations]
  );

  const relationCandidateItems = useMemo(() => {
    const base = relationQuery.trim() ? relationSearchResults : relatedItems;
    const activeId = active?.raw_id;
    return base.filter((item) => item.raw_id !== activeId && !linkedRawIdSet.has(item.raw_id));
  }, [relationQuery, relationSearchResults, relatedItems, active?.raw_id, linkedRawIdSet]);

  const relationItemLookup = useMemo(() => {
    const map = new Map<number, KnowledgeItem>();
    for (const row of items) {
      map.set(row.raw_id, row);
    }
    for (const row of relatedItems) {
      map.set(row.raw_id, row);
    }
    for (const row of relationSearchResults) {
      map.set(row.raw_id, row);
    }
    return map;
  }, [items, relatedItems, relationSearchResults]);

  const linkedRelationsDisplay = useMemo(
    () =>
      linkedRelations.map((row) => ({
        ...row,
        item: relationItemLookup.get(row.item.raw_id) ?? row.item
      })),
    [linkedRelations, relationItemLookup]
  );

  const allVisibleSelected =
    displayItems.length > 0 &&
    displayItems.every((item) => selectedIds.has(item.raw_id));

  const applyLocale = useCallback((next: Locale) => {
    setLocale(next);
    persistStoredLocale(next);
    void patchUserProfile({ locale: next }).catch(() => {
      /* offline or backend starting */
    });
  }, [setLocale]);

  useEffect(() => {
    hydrateKnowledgeSortMode();
    const stored = loadStoredLocale();
    setLocale(stored);
    void getUserProfile()
      .then((profile) => {
        const fromProfile = profile.app?.locale === "en" ? "en" : "zh";
        setLocale(fromProfile);
        persistStoredLocale(fromProfile);
      })
      .catch(() => {
        /* use localStorage default */
      });
  }, [setLocale]);

  useEffect(() => {
    if (!isHotlist || hotlistSource !== "economist") {
      return;
    }
    let cancelled = false;
    void getEconomistWeeks(economistYear, locale).then((data) => {
      if (cancelled) {
        return;
      }
      setEconomistWeeks(data.weeks);
      if (data.weeks.length === 0) {
        return;
      }
      const preferred =
        data.weeks.find((w) => w.iso_week === economistWeek) ??
        data.weeks.find(
          (w) => w.iso_year === data.current_iso_year && w.iso_week === data.current_iso_week
        ) ??
        data.weeks[0];
      setEconomistWeek(preferred.iso_week);
      setHotlistDate(preferred.edition_date);
    });
    return () => {
      cancelled = true;
    };
  }, [isHotlist, hotlistSource, economistYear, locale]);

  async function loadReader(rawId: number): Promise<void> {
    try {
      const content = await getReaderContent(rawId);
      setReader(content);
    } catch {
      setReader(undefined);
    }
  }

  const canLoadRelated =
    !isHotlist &&
    !!active &&
    active.distill_status === "ok" &&
    !!(active.summary && active.summary.trim());

  useEffect(() => {
    if (!canLoadRelated || !active) {
      setRelatedItems([]);
      return;
    }
    const rawId = active.raw_id;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void getRelatedItems(rawId)
        .then((data) => {
          if (!cancelled) {
            setRelatedItems(data.items);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setRelatedItems([]);
            setMessage(error instanceof Error ? error.message : String(error));
          }
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // Refetch when switching item or when summary/distill first becomes available — not on unrelated active patches.
  }, [active?.raw_id, active?.distill_status, canLoadRelated]);

  function mapRelationRows(
    rawId: number,
    rows: Awaited<ReturnType<typeof getItemRelations>>["items"]
  ): LinkedRelation[] {
    return rows
      .map((row) => {
        if (row.other_item) {
          return {
            relationId: row.id,
            relationType: row.relation_type,
            note: row.note ?? null,
            item: row.other_item
          } as LinkedRelation;
        }
        const otherRawId = row.from_raw_id === rawId ? row.to_raw_id : row.from_raw_id;
        const title = row.from_raw_id === rawId ? row.to_title : row.from_title;
        const url = row.from_raw_id === rawId ? row.to_url : row.from_url;
        const platform = row.from_raw_id === rawId ? row.to_platform : row.from_platform;
        if (!otherRawId || !url) {
          return null;
        }
        const item = {
          raw_id: otherRawId,
          url,
          title: title ?? null,
          platform: platform ?? "manual",
          source: "manual",
          content_type: "article",
          ingested_at: null,
          summary: row.note ?? null,
          topics: [],
          prompt_version: null,
          distill_status: "ok",
          author: "On1y",
          author_avatar: "",
          author_url: "",
          cover_image: "",
          theme_id: null,
          theme: null,
          themes: [],
          tags: []
        } as KnowledgeItem;
        return {
          relationId: row.id,
          relationType: row.relation_type,
          note: row.note ?? null,
          item
        } as LinkedRelation;
      })
      .filter((row): row is LinkedRelation => row !== null);
  }

  async function reloadLinkedRelations(rawId: number): Promise<void> {
    const data = await getItemRelations(rawId);
    setLinkedRelations(mapRelationRows(rawId, data.items));
  }

  useEffect(() => {
    if (!active) {
      setLinkedRelations([]);
      setSelectedLinkedIds(new Set());
      setRelationSearchResults([]);
      setRelationQuery("");
      setSelectedRelationCandidateIds(new Set());
      setRelationPanelOpen(false);
      return;
    }
    let cancelled = false;
    void getItemRelations(active.raw_id)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setLinkedRelations(mapRelationRows(active.raw_id, data.items));
        setSelectedLinkedIds(new Set());
      })
      .catch(() => {
        if (!cancelled) {
          setLinkedRelations([]);
          setSelectedLinkedIds(new Set());
        }
      });
    return () => {
      cancelled = true;
    };
  }, [active?.raw_id]);

  async function handleRelatedLessRelevant(toRawId: number): Promise<void> {
    if (!active) {
      return;
    }
    try {
      await postRelatedLessRelevant(active.raw_id, toRawId);
      setRelatedItems((prev) => prev.filter((row) => row.raw_id !== toRawId));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleLinkItem(toRawId: number): Promise<void> {
    if (!active) {
      return;
    }
    try {
      await createItemRelation({
        from_raw_id: active.raw_id,
        to_raw_id: toRawId,
        relation_type: "obsidian_link",
        confidence: 1
      });
      await reloadLinkedRelations(active.raw_id);
      setRelationSearchResults((prev) => prev.filter((row) => row.raw_id !== toRawId));
      setSelectedRelationCandidateIds((prev) => {
        if (!prev.has(toRawId)) {
          return prev;
        }
        const next = new Set(prev);
        next.delete(toRawId);
        return next;
      });
      void loadReader(active.raw_id);
      setMessage(locale === "zh" ? "已建立关联" : "Linked");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleUnlinkItem(targetRawId: number): Promise<void> {
    if (!active) {
      return;
    }
    const relation = linkedRelations.find((row) => row.item.raw_id === targetRawId);
    if (!relation) {
      return;
    }
    try {
      await deleteItemRelation(relation.relationId, active.raw_id);
      await reloadLinkedRelations(active.raw_id);
      setMessage(locale === "zh" ? "已取消关联" : "Unlinked");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleUnlinkSelected(): Promise<void> {
    if (!active) {
      return;
    }
    const ids = Array.from(selectedLinkedIds);
    if (ids.length === 0) {
      return;
    }
    for (const rawId of ids) {
      // eslint-disable-next-line no-await-in-loop
      await handleUnlinkItem(rawId);
    }
    setSelectedLinkedIds(new Set());
  }

  async function handleConfirmRelationCandidates(): Promise<void> {
    const ids = Array.from(selectedRelationCandidateIds);
    if (ids.length === 0) {
      return;
    }
    for (const rawId of ids) {
      // eslint-disable-next-line no-await-in-loop
      await handleLinkItem(rawId);
    }
    setSelectedRelationCandidateIds(new Set());
  }

  useEffect(() => {
    if (!relationPanelOpen) {
      return;
    }
    const candidateIds = new Set(relationCandidateItems.map((item) => item.raw_id));
    setSelectedRelationCandidateIds((prev) => {
      if (prev.size === 0) {
        return prev;
      }
      const next = new Set<number>();
      for (const rawId of prev) {
        if (candidateIds.has(rawId)) {
          next.add(rawId);
        }
      }
      return next.size === prev.size ? prev : next;
    });
  }, [relationPanelOpen, relationCandidateItems]);

  useEffect(() => {
    if (!relationPanelOpen) {
      return;
    }
    // Opening relation panel should default to recommendation candidates.
    setRelationQuery("");
    setRelationSearchResults([]);
    setSelectedRelationCandidateIds(new Set());
  }, [relationPanelOpen]);

  useEffect(() => {
    if (!relationPanelOpen || !active) {
      return;
    }
    let cancelled = false;
    setRelationSearchPool([]);
    void (async () => {
      const seen = new Set<number>();
      let offset = 0;
      while (!cancelled) {
        const resp = await getKnowledgeItems({
          collection: "feed",
          limit: RELATION_SEARCH_BATCH_SIZE,
          offset
        });
        const chunk = resp.items;
        if (!chunk.length) {
          break;
        }
        const append: KnowledgeItem[] = [];
        for (const row of chunk) {
          if (seen.has(row.raw_id)) {
            continue;
          }
          seen.add(row.raw_id);
          append.push(row);
        }
        if (append.length > 0 && !cancelled) {
          setRelationSearchPool((prev) => [...prev, ...append]);
        }
        if (chunk.length < RELATION_SEARCH_BATCH_SIZE) {
          break;
        }
        offset += chunk.length;
      }
    })().catch(() => {
      if (!cancelled) {
        setRelationSearchPool([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [relationPanelOpen, active?.raw_id]);

  useEffect(() => {
    if (!relationPanelOpen) {
      return;
    }
    const q = relationQuery.trim();
    if (!q) {
      setRelationSearchResults([]);
      setRelationSearching(false);
      return;
    }
    let cancelled = false;
    setRelationSearching(true);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const resp = await getKnowledgeItems({ q, collection: "feed", limit: 200 });
          if (cancelled || !active) {
            return;
          }
          const linkedRawIds = new Set(linkedRelations.map((row) => row.item.raw_id));
          const backendCandidates = resp.items.filter(
            (row) => row.raw_id !== active.raw_id && !linkedRawIds.has(row.raw_id)
          );
          const needle = q.toLowerCase();
          const localPool = [...items, ...relationSearchPool];
          const mergedPool = new Map<number, KnowledgeItem>();
          for (const row of localPool) {
            mergedPool.set(row.raw_id, row);
          }
          const localHits = Array.from(mergedPool.values()).filter((row) => {
            if (row.raw_id === active.raw_id || linkedRawIds.has(row.raw_id)) {
              return false;
            }
            const tags = row.tags.map((tg) => tg.name).join(" ");
            const haystack = [row.title || "", row.summary || "", row.author || "", tags]
              .join(" ")
              .toLowerCase();
            return haystack.includes(needle);
          });
          const merged = new Map<number, KnowledgeItem>();
          for (const row of backendCandidates) {
            merged.set(row.raw_id, row);
          }
          for (const row of localHits) {
            if (!merged.has(row.raw_id)) {
              merged.set(row.raw_id, withLocalSearchHighlight(row, q));
            }
          }
          setRelationSearchResults(Array.from(merged.values()));
        } catch (error) {
          if (!cancelled) {
            setMessage(error instanceof Error ? error.message : String(error));
            setRelationSearchResults([]);
          }
        } finally {
          if (!cancelled) {
            setRelationSearching(false);
          }
        }
      })();
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [relationPanelOpen, relationQuery, active?.raw_id, linkedRelations, items, relationSearchPool, setMessage]);

  async function handleTranslateTranscript(): Promise<void> {
    if (!active) {
      return;
    }
    setMessage("");
    try {
      const result = await translateItemTranscript(active.raw_id);
      setReader((prev) =>
        prev
          ? {
              ...prev,
              translated_body_text: result.translated_body_text,
              can_translate: true
            }
          : prev
      );
      setMessage(ui("translationReady"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  const originalTextPanelProps = {
    bodyText: reader?.body_text ?? "",
    markdownText:
      active?.platform === "obsidian"
        ? (reader?.raw_body_text ?? reader?.body_text ?? "")
        : (reader?.body_text ?? ""),
    exportBaseName: active?.title || active?.url || "content",
    exportMdLabel: ui("exportMarkdown"),
    exportTxtLabel: ui("exportText"),
    locale,
    emptyLabel: ui("noReaderText"),
    expandLabel: ui("expandReader"),
    collapseLabel: ui("collapseReader"),
    translatedBodyText: reader?.translated_body_text,
    noSubtitleNotice: ui("noSubtitleNotice"),
    descriptionFallbackLabel: ui("descriptionFallback"),
    translateLabel: ui("translateToZh"),
    translatingLabel: ui("translating"),
    onTranslate:
      locale === "zh" && reader?.can_translate && !reader?.translated_body_text
        ? handleTranslateTranscript
        : undefined
  } as const;

  const hideAiSummary =
    (reader?.body_text ?? "").trim().length > 0 &&
    (reader?.body_text ?? "").trim().length < SHORT_CONTENT_SUMMARY_MAX_CHARS;

  const isConversation =
    active?.platform === "telegram" || Boolean(reader?.is_conversation);
  const chatWriteUp =
    (reader?.reader_text ?? "").trim() || (active?.summary ?? "").trim();

  function buildItemsQuery(offset: number, limit = FEED_BATCH_SIZE) {
    return {
      locale,
      themeId: isHotlist ? undefined : selectedThemeId,
      creatorKey: isHotlist ? undefined : selectedCreatorKey,
      tagId: isHotlist ? undefined : selectedTagId,
      q: isHotlist ? undefined : query,
      platform: isHotlist ? undefined : filterValue(platform),
      collection: (isFeedBrowse || isBooks || isPapers ? "feed" : collection) as
        | "feed"
        | "favorites"
        | "trash"
        | "hotlist"
        | "notes"
        | "chats",
      hotlistDate: isHotlist ? hotlistDate : undefined,
      hotlistSource: isHotlist ? hotlistSource : undefined,
      feedDate: isFeedBrowse && feedDate ? feedDate : undefined,
      unreadOnly: isFeedBrowse && unreadOnly,
      minImportance: isFeedBrowse && minImportance ? minImportance : undefined,
      limit,
      offset
    };
  }

  function applyReadLocally(rawId: number, readAt: string | null): void {
    const patch = (row: KnowledgeItem): KnowledgeItem => ({
      ...row,
      read_at: readAt,
      is_read: Boolean(readAt)
    });
    if (readAt && unreadOnly) {
      const remaining = items.filter((row) => row.raw_id !== rawId).map((row) => patch(row));
      setItems(remaining);
      const next = active?.raw_id === rawId ? remaining[0] : remaining.find((r) => r.raw_id === active?.raw_id);
      setActive(next);
      if (next) {
        void loadReader(next.raw_id);
      } else {
        setReader(undefined);
      }
    } else {
      setItems((prev) => prev.map((row) => (row.raw_id === rawId ? patch(row) : row)));
      setActive((prev) => (prev?.raw_id === rawId ? patch(prev) : prev));
    }
    setCollectionCounts((prev) => ({
      ...prev,
      unread: readAt
        ? Math.max(0, prev.unread - 1)
        : prev.unread + (items.some((row) => row.raw_id === rawId && !row.read_at) ? 0 : 1)
    }));
  }

  async function handleMarkItemRead(rawId: number): Promise<void> {
    try {
      const result = await markItemRead(rawId);
      applyReadLocally(rawId, result.read_at);
    } catch {
      /* best effort */
    }
  }

  function handleOpenOriginalLink(
    event: React.MouseEvent<HTMLAnchorElement>,
    url: string,
    rawId: number
  ): void {
    void handleMarkItemRead(rawId);
    handleExternalLinkClick(event, url);
  }

  async function handleMarkUnread(): Promise<void> {
    if (!active) {
      return;
    }
    try {
      const result = await patchItemRead(active.raw_id, false);
      applyReadLocally(active.raw_id, result.read_at);
      setMessage(ui("markUnread"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "mark unread failed");
    }
  }

  function handleFeedDateSelect(date: string | null): void {
    setFeedDate(date);
    if (date) {
      const [y, m] = date.split("-").map(Number);
      if (y && m) {
        setCalendarMonth(new Date(y, m - 1, 1));
      }
    }
  }

  const hasMoreItems =
    itemTotal !== undefined &&
    items.length > 0 &&
    items.length < itemTotal;

  async function loadMoreItems(): Promise<boolean> {
    if (loadingMoreRef.current || loading || !hasMoreItems) {
      return false;
    }
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const itemResp = await getKnowledgeItems(buildItemsQuery(items.length));
      const total = itemResp.total ?? itemResp.count;
      setItemTotal(total);
      setItems((prev) => [...prev, ...itemResp.items]);
      if (query.trim()) {
        setSearchTotal(itemResp.total);
        setSearchEngine(itemResp.engine);
      }
      return itemResp.items.length > 0;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "load failed");
      return false;
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  function handleFeedScroll(event: React.UIEvent<HTMLDivElement>): void {
    const node = event.currentTarget;
    if (node.scrollTop + node.clientHeight < node.scrollHeight - 320) {
      return;
    }
    void loadMoreItems();
  }

  useEffect(() => {
    if (loading || loadingMore) {
      return;
    }
    const node = feedScrollRef.current;
    if (!node) {
      return;
    }
    if (itemTotal !== undefined && items.length >= itemTotal) {
      return;
    }
    if (node.scrollHeight <= node.clientHeight + 64) {
      void loadMoreItems();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length, itemTotal, loading, loadingMore, collection, selectedThemeId, selectedCreatorKey]);

  function feedCountLabel(): string {
    const loaded = String(displayItems.length);
    if (itemTotal !== undefined) {
      return ui("feedItemCount").replace("{loaded}", loaded).replace("{total}", String(itemTotal));
    }
    return `(${loaded})`;
  }

  async function applyItemResponse(
    itemResp: Awaited<ReturnType<typeof getKnowledgeItems>>,
    options?: { loadReader?: boolean }
  ): Promise<void> {
    setItems(itemResp.items);
    setItemTotal(itemResp.total ?? itemResp.count);
    setSearchTotal(itemResp.total);
    setSearchEngine(itemResp.engine);
    if (itemResp.items.length > 0) {
      const stillExists = itemResp.items.find((x) => x.raw_id === active?.raw_id);
      const next = stillExists ?? itemResp.items[0];
      setActive(next);
      setTagList(next.tags.map((tg) => tg.name));
      if (options?.loadReader !== false && !stillExists) {
        void loadReader(next.raw_id);
      }
    } else {
      setActive(undefined);
      setReader(undefined);
    }
  }

  async function refreshFeed(): Promise<void> {
    setLoading(true);
    setMessage("");
    setItems([]);
    setItemTotal(undefined);
    setActive(undefined);
    setReader(undefined);
    loadingMoreRef.current = false;
    setLoadingMore(false);
    try {
      const itemResp = await getKnowledgeItems(buildItemsQuery(0));
      await applyItemResponse(itemResp);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  async function refreshData(): Promise<void> {
    setLoading(true);
    setMessage("");
    loadingMoreRef.current = false;
    setLoadingMore(false);
    try {
      const taxonomy = await getTaxonomy(locale);
      setThemes(taxonomy.themes);
      setDynamicTags(taxonomy.tags);
      const itemResp = await getKnowledgeItems(buildItemsQuery(0, INITIAL_FEED_BATCH));
      await applyItemResponse(itemResp);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "load failed");
    } finally {
      setLoading(false);
    }

    void Promise.all([
      getCreators({ enrichAvatars: false }),
      getCollectionCounts(isHotlist ? { hotlistDate, hotlistSource } : undefined)
    ])
      .then(([creatorsResp, counts]) => {
        setCreators(creatorsResp.creators);
        setCollectionCounts(counts);
      })
      .catch(() => {
        /* sidebar badges can load later */
      });
  }

  const startColdStartJob = useCallback(async (): Promise<boolean> => {
    try {
      const cookies = await getCookieStatuses();
      if (!hasSyncCookies(cookies.platforms)) {
        setMessage(
          locale === "zh"
            ? "请先配置至少一个平台 Cookie（哔哩哔哩 / YouTube / 知乎）"
            : "Configure at least one platform cookie (Bilibili / YouTube / Zhihu) first"
        );
        return false;
      }
      const result = await runFullSync();
      if (!result.started && result.message) {
        setMessage(result.message);
      }
      const status = await getFullSyncStatus();
      setColdStartStatus(status);
      if (status.error) {
        setMessage(status.error);
      }
      try {
        sessionStorage.removeItem("on1y-cold-start-panel-dismissed");
      } catch {
        /* ignore */
      }
      return true;
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
      return false;
    }
  }, [locale]);

  useEffect(() => {
    void refreshData();
    void (async () => {
      try {
        const [status, profile] = await Promise.all([getFullSyncStatus(), getUserProfile()]);
        setColdStartStatus(status);
        if (status.error) {
          setMessage(status.error);
        }
        let autoStart = false;
        try {
          autoStart = sessionStorage.getItem("on1y-auto-cold-start") === "1";
          if (autoStart) {
            sessionStorage.removeItem("on1y-auto-cold-start");
          }
        } catch {
          /* ignore */
        }
        if (autoStart && !status.running && !status.active) {
          await startColdStartJob();
        } else if (!status.running && !status.active) {
          const cold = profile.cold_start;
          if (!cold?.onboarding_dismissed && !cold?.last_completed_at) {
            setColdStartOnboardingOpen(true);
          }
        }
      } catch {
        /* ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, startColdStartJob]);

  useEffect(() => {
    const onRequestSync = (): void => {
      void startColdStartJob();
    };
    const onSettingsClosed = (): void => {
      setBooksRefreshKey((k) => k + 1);
      setPapersRefreshKey((k) => k + 1);
      void (async () => {
        try {
          const profile = await getUserProfile();
          const cold = profile.cold_start;
          if (!cold?.onboarding_dismissed && !cold?.last_completed_at) {
            setColdStartOnboardingOpen(true);
          }
        } catch {
          /* ignore */
        }
      })();
    };
    const onShowGuide = (): void => {
      setColdStartOnboardingOpen(true);
    };
    window.addEventListener(REQUEST_INITIAL_SYNC_EVENT, onRequestSync);
    window.addEventListener(SETTINGS_CLOSED_EVENT, onSettingsClosed);
    window.addEventListener(SHOW_FIRST_RUN_GUIDE_EVENT, onShowGuide);
    return () => {
      window.removeEventListener(REQUEST_INITIAL_SYNC_EVENT, onRequestSync);
      window.removeEventListener(SETTINGS_CLOSED_EVENT, onSettingsClosed);
      window.removeEventListener(SHOW_FIRST_RUN_GUIDE_EVENT, onShowGuide);
    };
  }, [startColdStartJob]);

  const coldStartActive =
    Boolean(coldStartStatus?.active) ||
    Boolean(coldStartStatus?.running) ||
    Boolean(coldStartStatus?.subscription_sync?.running) ||
    Boolean(coldStartStatus?.background_distill?.running);

  const syncPanelResident =
    Boolean(coldStartStatus?.resident_panel) || Boolean(coldStartStatus?.pending_work);

  useEffect(() => {
    if (!coldStartActive && !syncPanelResident) {
      return;
    }
    const poll = async (): Promise<void> => {
      try {
        const status = await getFullSyncStatus();
        setColdStartStatus(status);
        if (status.error) {
          setMessage(status.error);
        }
        if (!coldStartActive) {
          return;
        }
        const [itemResp, taxonomy, creatorsResp] = await Promise.all([
          getKnowledgeItems(buildItemsQuery(0, INITIAL_FEED_BATCH)),
          getTaxonomy(locale),
          getCreators({ enrichAvatars: false })
        ]);
        setItems(itemResp.items);
        setItemTotal(itemResp.total ?? itemResp.count);
        setThemes(taxonomy.themes);
        setDynamicTags(taxonomy.tags);
        setCreators(creatorsResp.creators);
      } catch {
        /* background poll */
      }
    };
    void poll();
    const intervalMs = coldStartActive ? 4000 : syncPanelResident ? 5000 : 30000;
    const timer = window.setInterval(() => {
      void poll();
    }, intervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    coldStartActive,
    syncPanelResident,
    locale,
    collection,
    hotlistDate,
    hotlistSource,
    selectedThemeId,
    selectedCreatorKey,
    selectedTagId,
    platform,
    query,
    feedDate,
    unreadOnly,
    minImportance
  ]);

  useEffect(() => {
    if (!isFeedBrowse) {
      return;
    }
    let cancelled = false;
    void getStatsOverview(120)
      .then((stats) => {
        if (cancelled) {
          return;
        }
        const counts = new Map<string, number>();
        for (const row of stats.timeline) {
          if (row.total > 0) {
            counts.set(row.date, row.total);
          }
        }
        setFeedDayCounts(counts);
      })
      .catch(() => {
        /* optional */
      });
    return () => {
      cancelled = true;
    };
  }, [isFeedBrowse, locale]);

  const feedFiltersReadyRef = useRef(false);
  useEffect(() => {
    if (!feedFiltersReadyRef.current) {
      feedFiltersReadyRef.current = true;
      return;
    }
    if (isBooks || isPapers) {
      return;
    }
    let cancelled = false;
    const delay = query.trim() ? 300 : 0;
    const timer = window.setTimeout(() => {
      if (!cancelled) {
        void refreshFeed();
      }
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedThemeId,
    selectedCreatorKey,
    selectedTagId,
    platform,
    query,
    collection,
    hotlistDate,
    hotlistSource,
    feedDate,
    unreadOnly,
    minImportance
  ]);

  async function selectItem(item: KnowledgeItem): Promise<void> {
    setReaderExpanded(false);
    setActive(item);
    setTagList(item.tags.map((tg) => tg.name));
    if (!item.read_at && !item.is_read) {
      void handleMarkItemRead(item.raw_id);
    }
    await loadReader(item.raw_id);
  }

  async function handleThemeMoveForItem(rawId: number, themeId: number): Promise<void> {
    try {
      await moveItemTheme(rawId, themeId);
      setMessage(ui("themeMoved"));
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "move failed");
    }
  }

  async function handleToggleFavorite(item: KnowledgeItem): Promise<void> {
    const nextStarred = !item.starred;
    try {
      await toggleItemFavorite(item.raw_id, nextStarred);
      if (isFavorites && !nextStarred) {
        setMessage(ui("unfavorite"));
        await refreshData();
        return;
      }
      setItems((prev) =>
        prev.map((row) =>
          row.raw_id === item.raw_id ? { ...row, starred: nextStarred } : row
        )
      );
      if (active?.raw_id === item.raw_id) {
        setActive({ ...item, starred: nextStarred });
      }
      setMessage(nextStarred ? ui("favorite") : ui("unfavorite"));
      void getCollectionCounts().then(setCollectionCounts);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "favorite failed");
    }
  }

  async function handleRestoreItem(rawId: number): Promise<void> {
    try {
      await restoreKnowledgeItem(rawId);
      setMessage(locale === "zh" ? "已恢复" : "Restored");
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(rawId);
        return next;
      });
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "restore failed");
    }
  }

  async function handleDeleteItem(rawId: number): Promise<void> {
    try {
      await deleteKnowledgeItem(rawId);
      setMessage(isTrash ? (locale === "zh" ? "已永久删除" : "Permanently deleted") : locale === "zh" ? "已移至最近删除" : "Moved to trash");
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(rawId);
        return next;
      });
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "delete failed");
    }
  }

  function handleToggleSelect(rawId: number): void {
    if (!selectionMode) {
      setSelectionMode(true);
      setSelectedIds(new Set([rawId]));
      return;
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(rawId)) {
        next.delete(rawId);
      } else {
        next.add(rawId);
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
    setSelectedIds(new Set(displayItems.map((item) => item.raw_id)));
  }

  function clearSelection(): void {
    setSelectedIds(new Set());
    setBatchDeleteConfirm(false);
  }

  function exitSelectionMode(): void {
    setSelectionMode(false);
    clearSelection();
  }

  function switchCollection(next: KnowledgeCollection): void {
    exitSelectionMode();
    setItems([]);
    setItemTotal(undefined);
    setActive(undefined);
    setReader(undefined);
    setActiveBook(null);
    setActiveEdition(null);
    setManualAddBook(false);
    setActivePaper(null);
    setManualAddPaper(false);
    if (next !== "feed") {
      setFeedDate(null);
      setUnreadOnly(false);
    }
    setCollection(next);
    if (next === "hotlist") {
      setPlatform(ALL_FILTER);
      setQuery("");
      if (hotlistSource === "zhihu") {
        setHotlistDate(todayIsoDate());
      }
    } else if (sortMode === "hot_rank_asc") {
      setSortMode("published_desc");
    }
  }

  function selectEconomistWeek(week: number): void {
    setEconomistWeek(week);
    const row = economistWeeks.find((w) => w.iso_week === week);
    if (row) {
      setHotlistDate(row.edition_date);
    }
  }

  async function goEconomistCurrentWeek(): Promise<void> {
    const data = await getEconomistWeeks(undefined, locale);
    setEconomistYear(data.year);
    setEconomistWeeks(data.weeks);
    const cur =
      data.weeks.find(
        (w) => w.iso_year === data.current_iso_year && w.iso_week === data.current_iso_week
      ) ?? data.weeks[0];
    if (cur) {
      setEconomistWeek(cur.iso_week);
      setEconomistYear(cur.iso_year);
      setHotlistDate(cur.edition_date);
    }
  }

  async function handleHotlistSync(): Promise<void> {
    setLoading(true);
    try {
      const report = await runHotlistSync({
        sources: [hotlistSource],
        snapshot_date: hotlistDate,
        auto_tag: true
      });
      const row = report.results?.[hotlistSource];
      const tagged = row?.tagged ?? 0;
      setMessage(
        `${ui("hotlistSyncDone")}: +${row?.created ?? 0} / ↻${row?.updated ?? 0}${
          tagged > 0 ? ` · ${ui("hotlistTagged")} ${tagged}` : ""
        }`
      );
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "hotlist sync failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleBatchFavorite(): Promise<void> {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      return;
    }
    const selected = ids
      .map((rawId) => items.find((item) => item.raw_id === rawId))
      .filter((row): row is KnowledgeItem => row !== undefined);
    const allStarred = selected.length > 0 && selected.every((row) => row.starred);
    const targetStarred = !allStarred;

    setLoading(true);
    try {
      for (const row of selected) {
        if (row.starred !== targetStarred) {
          await toggleItemFavorite(row.raw_id, targetStarred);
        }
      }
      setMessage(
        targetStarred
          ? locale === "zh"
            ? `已收藏 ${selected.length} 条`
            : `Favorited ${selected.length} items`
          : locale === "zh"
            ? `已取消收藏 ${selected.length} 条`
            : `Unfavorited ${selected.length} items`
      );
      if (isFavorites && !targetStarred) {
        exitSelectionMode();
      }
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "favorite failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleBatchMoveTheme(themeId: number): Promise<void> {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      return;
    }
    setLoading(true);
    try {
      for (const rawId of ids) {
        await moveItemTheme(rawId, themeId);
      }
      setMessage(ui("batchMoved").replace("{n}", String(ids.length)));
      exitSelectionMode();
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "move failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleBatchDelete(): Promise<void> {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      return;
    }
    setLoading(true);
    try {
      const result = await batchDeleteKnowledgeItems(ids);
      setMessage(ui("batchDeleted").replace("{n}", String(result.deleted)));
      exitSelectionMode();
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "delete failed");
    } finally {
      setLoading(false);
      setBatchDeleteConfirm(false);
    }
  }

  async function saveTags(tags: string[]): Promise<void> {
    if (!active) {
      return;
    }
    try {
      await patchItemClassification(active.raw_id, {
        theme_slug: active.theme?.slug,
        tags
      });
      setMessage(ui("saveClassification"));
      const taxonomy = await getTaxonomy(locale);
      setDynamicTags(taxonomy.tags);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "save failed");
    }
  }

  async function handleTagsChange(tags: string[]): Promise<void> {
    setTagList(tags);
    await saveTags(tags);
  }

  async function handleSaveNote(html: string): Promise<void> {
    if (!active) {
      return;
    }
    await saveItemNote(active.raw_id, html);
    invalidateNotePreviewCache(active.raw_id);
    const hasNote = Boolean(html.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").trim());
    setReader((prev) => (prev ? { ...prev, user_note_html: html } : prev));
    setActive((prev) => (prev && prev.raw_id === active.raw_id ? { ...prev, has_note: hasNote } : prev));
    setItems((prev) =>
      prev.map((row) => (row.raw_id === active.raw_id ? { ...row, has_note: hasNote } : row))
    );
    void getCollectionCounts().then(setCollectionCounts);
    setMessage(ui("saveNote"));
  }

  async function handleSaveImportance(importance: number | null): Promise<void> {
    if (!active) {
      return;
    }
    try {
      const result = await patchItemImportance(active.raw_id, importance);
      const nextImportance = result.importance ?? null;
      const patch = (row: KnowledgeItem): KnowledgeItem => ({ ...row, importance: nextImportance });
      if (minImportance && (!nextImportance || nextImportance < minImportance)) {
        const remaining = items.filter((row) => row.raw_id !== active.raw_id);
        setItems(remaining);
        const next =
          active?.raw_id === active.raw_id
            ? remaining[0]
            : remaining.find((row) => row.raw_id === active?.raw_id);
        setActive(next);
        if (next) {
          void loadReader(next.raw_id);
        } else {
          setReader(undefined);
        }
      } else {
        setItems((prev) => prev.map((row) => (row.raw_id === active.raw_id ? patch(row) : row)));
        setActive((prev) => (prev?.raw_id === active.raw_id ? patch(prev) : prev));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleUploadFile(file: File): Promise<void> {
    await uploadDocument(file, true);
    setMessage(ui("uploadClassify"));
    await refreshData();
  }

  async function handleCreateTheme(name: string, description: string): Promise<void> {
    try {
      const result = await createTheme(
        {
          name_zh: name,
          name_en: name,
          description_zh: description,
          description_en: description
        },
        locale
      );
      await refreshData();
      let absorb = result.absorb;
      if (result.theme?.id && !absorb?.started) {
        try {
          absorb = await absorbThemeFromOther(result.theme.id, locale);
        } catch {
          /* older backend without absorb endpoint */
        }
      }
      if (absorb?.started) {
        setMessage(ui("themeAbsorbStarted"));
      } else if (absorb?.reason === "no_llm_key") {
        setMessage(ui("themeAbsorbNoLlm"));
      } else if (absorb?.reason === "already_running") {
        setMessage(ui("themeAbsorbStarted"));
      } else {
        setMessage(ui("addTheme"));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "create theme failed");
    }
  }

  async function handleDeleteTheme(themeId: number): Promise<{ remapped: number }> {
    const result = await deleteTheme(themeId);
    if (selectedThemeId === themeId) {
      setTheme(undefined);
    }
    await refreshData();
    setMessage(ui("themeDeleted").replace("{n}", String(result.remapped)));
    return { remapped: result.remapped };
  }

  async function handleReorderThemes(themeIds: number[]): Promise<void> {
    const before = themes.map((theme) => theme.id).join(",");
    const after = themeIds.join(",");
    if (before === after) {
      return;
    }
    const result = await reorderThemes(themeIds, locale);
    setThemes(result.themes);
  }

  async function handleUpdateThemeDescription(
    themeId: number,
    description: string
  ): Promise<void> {
    try {
      const result = await updateTheme(
        themeId,
        {
          description_zh: description,
          description_en: description
        },
        locale
      );
      const row = result.theme;
      setThemes((prev) =>
        prev.map((theme) =>
          theme.id === themeId
            ? {
                ...theme,
                description_zh: row.description_zh ?? theme.description_zh,
                description_en: row.description_en ?? theme.description_en
              }
            : theme
        )
      );
      const absorb = result.absorb;
      if (absorb?.started) {
        setMessage(ui("themeAbsorbOnDescSaved"));
      } else if (absorb?.reason === "no_llm_key") {
        setMessage(ui("themeAbsorbNoLlm"));
      } else {
        setMessage(ui("themeDescSaved"));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "update theme failed");
      throw error;
    }
  }

  const tagSuggestions = useMemo(
    () => dynamicTags.map((tag) => tag.name),
    [dynamicTags]
  );

  const notesPanelLabels = {
    notes: ui("notes"),
    notesPlaceholder: ui("notesPlaceholder"),
    saveNote: ui("saveNote"),
    ratePrompt: ui("ratePrompt"),
    notePreviewEmpty: ui("notePreviewEmpty"),
    upload: ui("upload"),
    chooseFile: ui("chooseFile"),
    uploadClassify: ui("uploadClassify"),
    exportWord: ui("exportWord"),
    exportPdf: ui("exportPdf"),
    summary: ui("summary"),
    originalText: ui("originalText")
  };

  return (
    <>
    <div className="flex h-screen w-full flex-col bg-background text-foreground">
      <div className="shrink-0 border-b border-border bg-background px-4 py-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <img
              src="/on1y-logo.png"
              alt=""
              width={32}
              height={32}
              className="h-8 w-8 shrink-0 object-contain"
            />
            <h1 className="text-lg font-semibold tracking-tight">{ui("appTitle")}</h1>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/stats/"
              className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm hover:bg-soft"
            >
              <BarChart3 className="h-4 w-4" />
              {ui("stats")}
            </Link>
            <button
              type="button"
              onClick={() => void refreshData()}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm hover:bg-soft"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {ui("refresh")}
            </button>
            <EveningDigestButton locale={locale} />
            <AccountMenu locale={locale} onLocaleChange={applyLocale} onMessage={setMessage} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!isBooks && !isPapers ? (
          <div className="on1y-glass-trigger inline-flex items-center gap-2 rounded-md px-2 py-1.5">
            <Search className="h-4 w-4 text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={ui("searchPlaceholder")}
              className="w-56 bg-transparent text-sm text-foreground outline-none"
            />
          </div>
          ) : null}
          {!isBooks && !isPapers && query.trim() && searchTotal !== undefined ? (
            <span className="text-xs text-muted">
              {ui("searchResults").replace("{n}", String(searchTotal))}
              {searchEngine ? ` · ${searchEngine}` : ""}
            </span>
          ) : null}
          <FilterSelect
            placeholder={ui("platform")}
            value={platform}
            onChange={setPlatform}
            options={platformOptions}
          />
          <button
            type="button"
            onClick={() => void refreshData()}
            className="rounded-md border border-inverse bg-inverse px-3 py-1.5 text-sm text-inverse-foreground hover:opacity-90"
          >
            {ui("filter")}
          </button>
          {message ? <span className="text-sm text-muted">{message}</span> : null}
        </div>
      </div>

      <AppUpdateBanner locale={locale} />
      <PipelineAlertsBanner locale={locale} />
      {isBooks ? (
        <BookAcquireNoticeBar
          locale={locale}
          notice={bookAcquireNotice}
          onDismiss={() => setBookAcquireNotice(null)}
        />
      ) : null}

      {readerExpanded && active ? (
        <PanelGroup key="reader-expanded" direction="horizontal" className="min-h-0 flex-1">
          <Panel minSize={25} defaultSize={58} className="min-h-0 overflow-hidden">
            <div className="flex h-full min-h-0 flex-col border-r border-border bg-surface p-4">
              <div className="mb-3 shrink-0">
                <h3 className="text-lg font-semibold leading-snug">{active.title || "—"}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>{platformLabel(active.platform, locale)}</span>
                  <a
                    href={active.url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => handleOpenOriginalLink(e, active.url, active.raw_id)}
                    className="inline-flex items-center gap-1 hover:text-foreground hover:underline"
                  >
                    {ui("openLink")}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
              {isConversation ? (
                <>
                  <div className="mb-4 shrink-0 rounded-md border border-border bg-panel px-4 py-3">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                      {ui("chatWriteUp")}
                    </p>
                    {chatWriteUp ? (
                      <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                        {chatWriteUp}
                      </div>
                    ) : (
                      <p className="text-sm text-muted">{ui("chatWriteUpEmpty")}</p>
                    )}
                  </div>
                  <ConversationTranscriptPanel
                    locale={locale}
                    bodyText={reader?.body_text ?? ""}
                    structured={reader?.telegram_messages}
                    emptyLabel={ui("noReaderText")}
                    expandLabel={ui("expandReader")}
                    collapseLabel={ui("collapseReader")}
                    expanded
                    onCollapse={() => setReaderExpanded(false)}
                  />
                </>
              ) : (
                <OriginalTextPanel
                  {...originalTextPanelProps}
                  expanded
                  onCollapse={() => setReaderExpanded(false)}
                />
              )}
            </div>
          </Panel>
          <PanelResizeHandle className="w-px bg-border" />
          <Panel minSize={20} defaultSize={42} className="min-h-0 overflow-hidden">
            <div className="h-full min-h-0 p-3">
              <NotesPanel
                rawId={active.raw_id}
                title={active.title || active.url}
                summary={active.summary || ""}
                bodyText={reader?.body_text ?? ""}
                translatedBodyText={reader?.translated_body_text}
                noteHtml={reader?.user_note_html ?? ""}
                importance={active.importance ?? null}
                locale={locale}
                labels={notesPanelLabels}
                onSaveNote={handleSaveNote}
                onImportanceChange={handleSaveImportance}
                onUpload={handleUploadFile}
              />
            </div>
          </Panel>
        </PanelGroup>
      ) : (
        <PanelGroup key="normal" direction="horizontal" className="min-h-0 flex-1">
        <Panel minSize={15} defaultSize={18} className="min-h-0 overflow-hidden">
          <ColumnScroll className="border-r border-border p-3">
              <div className={`mb-3 flex rounded-md p-0.5 ${GLASS_PANEL}`}>
                <button
                  type="button"
                  onClick={() => setSidebarMode("theme")}
                  className={`flex-1 rounded-md px-2 py-1 text-xs transition-colors ${glassNavClass(
                    sidebarMode === "theme",
                    sidebarMode !== "theme" ? "text-muted hover:text-foreground" : ""
                  )}`}
                >
                  {ui("sidebarTheme")}
                </button>
                <button
                  type="button"
                  onClick={() => setSidebarMode("creator")}
                  className={`flex-1 rounded-md px-2 py-1 text-xs transition-colors ${glassNavClass(
                    sidebarMode === "creator",
                    sidebarMode !== "creator" ? "text-muted hover:text-foreground" : ""
                  )}`}
                >
                  {ui("sidebarCreator")}
                </button>
              </div>

              {sidebarMode === "theme" ? (
              <ThemeSidebar
                locale={locale}
                themes={themes}
                selectedThemeId={selectedThemeId}
                collection={collection}
                onSelectAll={() => {
                  exitSelectionMode();
                  selectTheme(undefined);
                }}
                onSelectTheme={(themeId) => {
                  exitSelectionMode();
                  selectTheme(themeId);
                }}
                onCreateTheme={handleCreateTheme}
                onDeleteTheme={async (themeId) => {
                  try {
                    return await handleDeleteTheme(themeId);
                  } catch (error) {
                    setMessage(
                      error instanceof Error ? error.message : "delete theme failed"
                    );
                    throw error;
                  }
                }}
                onReorderThemes={async (themeIds) => {
                  try {
                    await handleReorderThemes(themeIds);
                  } catch (error) {
                    setMessage(
                      error instanceof Error ? error.message : "reorder themes failed"
                    );
                    throw error;
                  }
                }}
                onUpdateThemeDescription={async (themeId, description) => {
                  try {
                    await handleUpdateThemeDescription(themeId, description);
                  } catch (error) {
                    throw error;
                  }
                }}
                labels={{
                  themes: ui("themes"),
                  allThemes: ui("allThemes"),
                  addTheme: ui("addTheme"),
                  themeName: ui("themeName"),
                  themeDesc: ui("themeDesc"),
                  editThemeDesc: ui("editThemeDesc"),
                  themeDescSave: ui("themeDescSave"),
                  themeDescCancel: ui("themeDescCancel"),
                  deleteTheme: ui("deleteTheme"),
                  confirmDeleteTheme: ui("confirmDeleteTheme"),
                  themeDeleted: ui("themeDeleted"),
                  cannotDeleteBuiltin: ui("cannotDeleteBuiltin"),
                  deletingTheme: ui("deletingTheme"),
                  done: ui("themeEditDone")
                }}
              />
              ) : (
              <CreatorSidebar
                locale={locale}
                creators={creators}
                selectedCreatorKey={selectedCreatorKey}
                onSelectAll={() => {
                  exitSelectionMode();
                  setCreator(undefined);
                }}
                onSelectCreator={(key) => {
                  exitSelectionMode();
                  selectCreator(key);
                }}
                labels={{
                  creators: ui("creators"),
                  allCreators: ui("allCreators"),
                  empty: ui("creatorsEmpty")
                }}
              />
              )}

              <div className="mb-4 mt-4 border-t border-border pt-3">
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  {locale === "zh" ? "专栏" : "Collections"}
                </h2>
                <div className="space-y-0.5">
                  <button
                    type="button"
                    onClick={() => switchCollection("notes")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isNotes
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <NotebookPen className="h-3.5 w-3.5" />
                      {ui("collectionNotes")}
                    </span>
                    <span className={`text-xs ${isNotes ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.notes}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("chats")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isChats
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <MessageCircle className="h-3.5 w-3.5" />
                      {ui("collectionChats")}
                    </span>
                    <span className={`text-xs ${isChats ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.chats}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("books")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isBooks
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <BookOpen className="h-3.5 w-3.5" />
                      {ui("collectionBooks")}
                    </span>
                    <span className={`text-xs ${isBooks ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.books}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("papers")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isPapers
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <FileText className="h-3.5 w-3.5" />
                      {ui("collectionPapers")}
                    </span>
                    <span className={`text-xs ${isPapers ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.papers}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("hotlist")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isHotlist
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Flame className="h-3.5 w-3.5" />
                      {ui("collectionHotlist")}
                    </span>
                    <span className={`text-xs ${isHotlist ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.hotlist}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("favorites")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isFavorites
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Star className="h-3.5 w-3.5" />
                      {ui("collectionFavorites")}
                    </span>
                    <span className={`text-xs ${isFavorites ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.favorites}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchCollection("trash")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isTrash
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Trash2 className="h-3.5 w-3.5" />
                      {ui("collectionTrash")}
                    </span>
                    <span className={`text-xs ${isTrash ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.trash}
                    </span>
                  </button>
                </div>
              </div>
          </ColumnScroll>
        </Panel>

        <PanelResizeHandle className="w-px bg-border" />

        <Panel minSize={20} defaultSize={24} className="min-h-0 overflow-hidden">
          {isBooks ? (
            <div className="flex h-full min-h-0 flex-col border-r border-border p-3">
              <h2 className="mb-3 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">
                {ui("collectionBooks")} ({collectionCounts.books})
              </h2>
              <div className="min-h-0 flex-1">
                <BooksListColumn
                  key={booksRefreshKey}
                  locale={locale}
                  activeId={manualAddBook ? null : activeBook?.id ?? null}
                  activeEditionId={manualAddBook ? null : activeEdition?.edition_id ?? null}
                  manualAdd={manualAddBook}
                  onAcquireNotice={setBookAcquireNotice}
                  onSelect={(item) => {
                    setManualAddBook(false);
                    setActiveEdition(null);
                    setActiveBook(item);
                  }}
                  onSelectEdition={(edition) => {
                    setManualAddBook(false);
                    setActiveBook(null);
                    setActiveEdition(edition);
                  }}
                  onStartManualAdd={() => {
                    setActiveBook(null);
                    setActiveEdition(null);
                    setManualAddBook(true);
                  }}
                  onShelfChanged={() => {
                    setBooksRefreshKey((k) => k + 1);
                    void getCollectionCounts().then(setCollectionCounts);
                  }}
                  onEditionShelfAdded={(item) => {
                    setManualAddBook(false);
                    setActiveEdition(null);
                    setActiveBook(item);
                    setBooksRefreshKey((k) => k + 1);
                    void getCollectionCounts().then(setCollectionCounts);
                  }}
                  onItemUpdated={(item) => {
                    if (activeBook?.id === item.id) {
                      setActiveBook(item);
                    }
                  }}
                  onRemoved={(id) => {
                    if (activeBook?.id === id) {
                      setActiveBook(null);
                    }
                    setBooksRefreshKey((k) => k + 1);
                    void getCollectionCounts().then(setCollectionCounts);
                  }}
                  onMessage={setMessage}
                />
              </div>
            </div>
          ) : isPapers ? (
            <div className="flex h-full min-h-0 flex-col border-r border-border p-3">
              <h2 className="mb-3 shrink-0 text-xs font-medium uppercase tracking-wider text-muted">
                {ui("collectionPapers")} ({collectionCounts.papers})
              </h2>
              <div className="min-h-0 flex-1">
                <PapersListColumn
                  locale={locale}
                  activeId={manualAddPaper ? null : activePaper?.id ?? null}
                  refreshKey={papersRefreshKey}
                  onSelect={(item) => {
                    setManualAddPaper(false);
                    setActivePaper(item);
                  }}
                  onStartManualAdd={() => {
                    setActivePaper(null);
                    setManualAddPaper(true);
                  }}
                  onChanged={() => {
                    setPapersRefreshKey((key) => key + 1);
                    void getCollectionCounts().then(setCollectionCounts);
                  }}
                  onRemoved={(id) => {
                    if (activePaper?.id === id) setActivePaper(null);
                    setPapersRefreshKey((key) => key + 1);
                    void getCollectionCounts().then(setCollectionCounts);
                  }}
                  onMessage={setMessage}
                />
              </div>
            </div>
          ) : (
          <ColumnScroll
            className="border-r border-border p-3"
            scrollRef={feedScrollRef}
            onScroll={handleFeedScroll}
          >
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xs font-medium uppercase tracking-wider text-muted">
                  {selectedCreator
                    ? ui("creatorFeed").replace("{name}", selectedCreator.name)
                    : isFavorites
                      ? ui("collectionFavorites")
                      : isNotes
                        ? ui("collectionNotes")
                      : isChats
                        ? ui("collectionChats")
                      : isTrash
                        ? ui("collectionTrash")
                        : isHotlist
                          ? ui("collectionHotlist")
                          : unreadOnly
                            ? ui("collectionUnread")
                          : feedDate
                            ? feedDate
                          : ui("feed")}{" "}
                  {feedCountLabel()}
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                {isHotlist ? (
                  <>
                    <FilterSelect
                      placeholder={ui("hotlistSourceLabel")}
                      value={hotlistSource}
                      onChange={(value) => {
                        const next = value as HotlistSource;
                        setHotlistSource(next);
                        if (next === "zhihu") {
                          setHotlistDate(todayIsoDate());
                        }
                      }}
                      options={[
                        { value: "zhihu", label: ui("hotlistSourceZhihu") },
                        { value: "economist", label: ui("hotlistSourceEconomist") }
                      ]}
                    />
                    {hotlistSource === "economist" ? (
                      <>
                        <label className="flex items-center gap-1.5 text-xs text-muted">
                          <span>{ui("hotlistYearLabel")}</span>
                          <select
                            value={economistYear}
                            onChange={(e) => setEconomistYear(Number(e.target.value))}
                            className="rounded border border-border bg-surface px-2 py-1 text-xs text-foreground"
                          >
                            {Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - i).map(
                              (y) => (
                                <option key={y} value={y}>
                                  {y}
                                </option>
                              )
                            )}
                          </select>
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-muted">
                          <span>{ui("hotlistWeekLabel")}</span>
                          <select
                            value={economistWeek}
                            onChange={(e) => selectEconomistWeek(Number(e.target.value))}
                            className="max-w-[12rem] rounded border border-border bg-surface px-2 py-1 text-xs text-foreground"
                          >
                            {economistWeeks.map((w) => (
                              <option key={`${w.iso_year}-${w.iso_week}`} value={w.iso_week}>
                                {w.label}
                                {w.synced
                                  ? locale === "zh"
                                    ? " · 已入库"
                                    : " · saved"
                                  : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          onClick={() => void goEconomistCurrentWeek()}
                          className="rounded border border-border bg-surface px-2 py-1 text-xs hover:bg-soft"
                        >
                          {ui("hotlistCurrentWeek")}
                        </button>
                      </>
                    ) : (
                      <>
                        <label className="flex items-center gap-1.5 text-xs text-muted">
                          <span>{ui("hotlistDateLabel")}</span>
                          <input
                            type="date"
                            value={hotlistDate}
                            max={todayIsoDate()}
                            onChange={(e) => setHotlistDate(e.target.value || todayIsoDate())}
                            className="rounded border border-border bg-surface px-2 py-1 text-xs text-foreground"
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => setHotlistDate(todayIsoDate())}
                          className="rounded border border-border bg-surface px-2 py-1 text-xs hover:bg-soft"
                        >
                          {ui("hotlistToday")}
                        </button>
                      </>
                    )}
                    {hotlistSource === "economist" ? (
                      <span className="hidden text-[10px] text-muted sm:inline">
                        {ui("hotlistSourceGithubHint")}
                      </span>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void handleHotlistSync()}
                      disabled={
                        loading ||
                        (hotlistSource === "zhihu" && hotlistDate !== todayIsoDate())
                      }
                      title={
                        hotlistSource === "zhihu" && hotlistDate !== todayIsoDate()
                          ? ui("hotlistSyncTodayOnly")
                          : undefined
                      }
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:bg-soft disabled:opacity-50"
                    >
                      <Flame className="h-3.5 w-3.5 text-orange-500" />
                      {hotlistSource === "economist"
                        ? ui("hotlistSyncEconomist")
                        : ui("hotlistSyncNow")}
                    </button>
                  </>
                ) : (
                  <>
                    {isFeedBrowse ? (
                      <>
                        <button
                          type="button"
                          onClick={() => setUnreadOnly((value) => !value)}
                          title={ui("feedUnreadFilter")}
                          aria-label={ui("feedUnreadFilter")}
                          aria-pressed={unreadOnly}
                          className={`flex h-8 items-center gap-1 rounded-md border px-2 text-xs transition-colors ${
                            unreadOnly
                              ? "border-accent/50 bg-accent/10 text-accent"
                              : "border-transparent text-muted hover:border-border hover:bg-soft hover:text-foreground"
                          }`}
                        >
                          <Inbox className="h-4 w-4" />
                          {collectionCounts.unread > 0 ? (
                            <span className="tabular-nums">{collectionCounts.unread}</span>
                          ) : null}
                        </button>
                        <FeedDatePicker
                        locale={locale}
                        month={calendarMonth}
                        selectedDate={feedDate}
                        dayCounts={feedDayCounts}
                        onMonthChange={setCalendarMonth}
                        onSelectDate={handleFeedDateSelect}
                        ariaLabel={ui("feedDatePicker")}
                        labels={{
                          clear: ui("feedDateClear"),
                          today: ui("feedDateToday")
                        }}
                      />
                        <FilterSelect
                          placeholder={ui("importanceFilter")}
                          value={minImportance ? String(minImportance) : ALL_FILTER}
                          onChange={(value) =>
                            setMinImportance(value === ALL_FILTER ? null : Number(value))
                          }
                          options={importanceFilterOptions}
                        />
                      </>
                    ) : null}
                    <FilterSelect
                      placeholder={ui("sortBy")}
                      value={sortMode}
                      onChange={(value) => setSortMode(value as typeof sortMode)}
                      options={sortOptions}
                    />
                  </>
                )}
                </div>
              </div>
              {selectionMode ? (
                <div className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-border bg-panel px-2 py-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={toggleSelectAllVisible}
                      title={ui("selectAll")}
                      aria-label={ui("selectAll")}
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
                      {ui("batchSelected").replace("{n}", String(selectedIds.size))}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    {isTrash ? null : (
                      <>
                        <button
                          type="button"
                          onClick={() => void handleBatchFavorite()}
                          disabled={selectedIds.size === 0 || loading}
                          title={ui("favorite")}
                          aria-label={ui("favorite")}
                          className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground disabled:opacity-40"
                        >
                          <Star className="h-4 w-4" />
                        </button>
                        <ThemeMovePopover
                          themes={themes}
                          locale={locale}
                          onSelect={(themeId) => void handleBatchMoveTheme(themeId)}
                          floatPanel
                          trigger={
                            <button
                              type="button"
                              disabled={selectedIds.size === 0 || loading}
                              title={ui("moveTheme")}
                              aria-label={ui("moveTheme")}
                              className="flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground disabled:opacity-40"
                            >
                              <Forward className="h-4 w-4" />
                            </button>
                          }
                        />
                      </>
                    )}
                    {batchDeleteConfirm ? (
                      <button
                        type="button"
                        onClick={() => void handleBatchDelete()}
                        disabled={selectedIds.size === 0 || loading}
                        title={ui("batchDeleteConfirm")}
                        aria-label={ui("batchDeleteConfirm")}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-red-600 hover:bg-red-50 disabled:opacity-40"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setBatchDeleteConfirm(true)}
                        disabled={selectedIds.size === 0 || loading}
                        title={ui("batchDelete")}
                        aria-label={ui("batchDelete")}
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
              <div className="space-y-2">
                {displayItems.map((item) => (
                  <FeedItemCard
                    key={item.raw_id}
                    item={item}
                    active={active?.raw_id === item.raw_id}
                    locale={locale}
                    themes={themes}
                    compact={isHotlist}
                    unknownAuthorLabel={ui("unknownAuthor")}
                    noSummaryLabel={ui("noSummary")}
                    moveThemeLabel={ui("moveTheme")}
                    favoriteLabel={ui("favorite")}
                    unfavoriteLabel={ui("unfavorite")}
                    deleteLabel={ui("deleteItem")}
                    deleteConfirmLabel={ui("deleteConfirm")}
                    batchSelectLabel={ui("batchSelect")}
                    trashMode={isTrash}
                    restoreLabel={ui("restoreItem")}
                    onRestore={() => void handleRestoreItem(item.raw_id)}
                    authorAvatar={
                      isHotlist ? undefined : (
                        <AuthorAvatar
                          author={item.author}
                          authorAvatar={resolveAuthorAvatar(item.author_avatar)}
                          unknownLabel={ui("unknownAuthor")}
                          size="md"
                        />
                      )
                    }
                    selectionMode={selectionMode}
                    selected={selectedIds.has(item.raw_id)}
                    onToggleSelected={() => handleToggleSelect(item.raw_id)}
                    onSelect={() => void selectItem(item)}
                    onMoveTheme={(themeId) => void handleThemeMoveForItem(item.raw_id, themeId)}
                    onToggleFavorite={() => void handleToggleFavorite(item)}
                    onDelete={() => void handleDeleteItem(item.raw_id)}
                    notePreviewHtml={active?.raw_id === item.raw_id ? reader?.user_note_html : undefined}
                    notePreviewEmptyLabel={ui("notePreviewEmpty")}
                  />
                ))}
                {displayItems.length === 0 ? (
                  <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
                    {loading
                      ? ui("loadingMore")
                      : isTrash
                        ? ui("trashEmpty")
                        : isFavorites
                          ? ui("favoritesEmpty")
                          : unreadOnly
                            ? ui("unreadEmpty")
                          : isNotes
                            ? ui("notesEmpty")
                          : isChats
                            ? ui("chatsEmpty")
                          : isHotlist
                            ? hotlistSource === "economist"
                              ? ui("hotlistEmptyEconomist")
                              : ui("hotlistEmpty")
                            : ui("noItems")}
                  </div>
                ) : null}
                {loadingMore ? (
                  <p className="py-3 text-center text-xs text-muted">{ui("loadingMore")}</p>
                ) : null}
              </div>
          </ColumnScroll>
          )}
        </Panel>
        <PanelResizeHandle className="w-px bg-border" />

        <Panel minSize={22} defaultSize={58} className="min-h-0 overflow-hidden">
          {isBooks ? (
            <BooksDetailColumn
              locale={locale}
              item={activeBook}
              edition={activeEdition}
              manualAdd={manualAddBook}
              onAcquireNotice={setBookAcquireNotice}
              onSaved={(item) => {
                setManualAddBook(false);
                setActiveEdition(null);
                setActiveBook(item);
              }}
              onDeleted={() => {
                setActiveBook(null);
                setBooksRefreshKey((k) => k + 1);
                void getCollectionCounts().then(setCollectionCounts);
              }}
              onCancelManual={() => setManualAddBook(false)}
              onMessage={setMessage}
              onSelectShelfItem={(id) => {
                void fetchBookShelfItem(id).then((row) => {
                  setManualAddBook(false);
                  setActiveEdition(null);
                  setActiveBook(row);
                });
              }}
              onSelectKnowledgeItem={(item) => {
                setManualAddBook(false);
                setActiveEdition(null);
                setActiveBook(null);
                switchCollection("feed");
                void selectItem(item);
              }}
            />
          ) : isPapers ? (
            <PapersDetailColumn
              locale={locale}
              item={activePaper}
              manualAdd={manualAddPaper}
              onSaved={(paper) => {
                setManualAddPaper(false);
                setActivePaper(paper);
                setPapersRefreshKey((key) => key + 1);
                void getCollectionCounts().then(setCollectionCounts);
              }}
              onCancelManual={() => setManualAddPaper(false)}
              onMessage={setMessage}
              onSelectPaper={(id) => {
                void fetchPaper(id).then((paper) => {
                  setManualAddPaper(false);
                  setActivePaper(paper);
                });
              }}
              onSelectKnowledgeItem={(item) => {
                setManualAddPaper(false);
                setActivePaper(null);
                switchCollection("feed");
                void selectItem(item);
              }}
            />
          ) : active ? (
            <ColumnScroll className="border-r border-border bg-surface">
              <div className="space-y-0">
              <div className="space-y-3 border-b border-border p-4">
                {!isHotlist
                  ? (() => {
                      const cover = resolveCover({
                        cover_image: reader?.cover_image ?? active.cover_image,
                        author_avatar: reader?.author_avatar ?? active.author_avatar
                      });
                      return cover ? (
                        <a
                          href={active.url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => handleOpenOriginalLink(e, active.url, active.raw_id)}
                          className="block overflow-hidden rounded-lg border border-border bg-panel"
                        >
                          <img
                            src={cover}
                            alt=""
                            className="aspect-video w-full object-cover"
                            referrerPolicy="no-referrer"
                          />
                        </a>
                      ) : null;
                    })()
                  : null}
                <div>
                  {!isHotlist ? (
                    <div className="mb-2 flex items-center gap-2">
                      <AuthorAvatar
                        author={reader?.author ?? active.author}
                        authorAvatar={resolveAuthorAvatar(
                          reader?.author_avatar ?? active.author_avatar
                        )}
                        unknownLabel={ui("unknownAuthor")}
                        size="sm"
                      />
                      {(reader?.author_url ?? active.author_url)?.trim() ? (
                        <a
                          href={reader?.author_url ?? active.author_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) =>
                            handleExternalLinkClick(e, reader?.author_url ?? active.author_url)
                          }
                          className="truncate text-sm font-medium text-foreground underline-offset-2 hover:underline"
                        >
                          {(reader?.author ?? active.author).trim() || ui("unknownAuthor")}
                        </a>
                      ) : (
                        <span className="truncate text-sm font-medium text-foreground">
                          {(reader?.author ?? active.author).trim() || ui("unknownAuthor")}
                        </span>
                      )}
                    </div>
                  ) : null}
                  <div className="flex items-start gap-2">
                    <h3 className="min-w-0 flex-1 text-base font-semibold leading-snug">
                      {active.title || "—"}
                    </h3>
                    <ContentTypeIndicator
                      contentType={active.content_type}
                      platform={active.platform}
                      locale={locale}
                      className="mt-1 shrink-0"
                    />
                  </div>
                  {isEconomistHotlist ? (
                    <a
                      href={economistEpubDownloadUrl(active.raw_id)}
                      download
                      className="mt-1.5 inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                    >
                      {ui("hotlistDownloadEpub")}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
                  <ActiveItemMeta item={active} locale={locale} ui={ui} />
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-xs text-muted">{ui("sourcePlatform")}</span>
                    <span className="rounded bg-soft px-2 py-0.5 text-xs font-medium text-foreground">
                      {platformLabel(active.platform, locale)}
                    </span>
                    {active.clip_source ? (
                      <span className="rounded bg-soft px-2 py-0.5 text-xs font-medium text-foreground">
                        {clipSourceLabel(active.clip_source, locale)}
                        {active.clip_count ? ` · ${active.clip_count}` : ""}
                      </span>
                    ) : null}
                    {active.extract_strategy ? (
                      <span className="rounded bg-soft px-2 py-0.5 text-xs font-medium text-foreground">
                        {extractStrategyLabel(active.extract_strategy, locale)}
                      </span>
                    ) : null}
                    {active.is_read || active.read_at ? (
                      <button
                        type="button"
                        onClick={() => void handleMarkUnread()}
                        className="text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {ui("markUnread")}
                      </button>
                    ) : null}
                    {!isEconomistHotlist ? (
                      <a
                        href={active.url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => handleOpenOriginalLink(e, active.url, active.raw_id)}
                        className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {ui("openLink")}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                    {active.platform === "obsidian" && reader?.obsidian_uri ? (
                      <a
                        href={reader.obsidian_uri}
                        onClick={(e) => handleExternalLinkClick(e, reader.obsidian_uri || "")}
                        className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {locale === "zh" ? "打开 Obsidian" : "Open in Obsidian"}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                    {active.platform === "obsidian" && reader?.obsidian_source_url ? (
                      <a
                        href={reader.obsidian_source_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => handleOpenOriginalLink(e, reader.obsidian_source_url || "", active.raw_id)}
                        className="inline-flex items-center gap-1 text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {locale === "zh" ? "原文链接" : "Original link"}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => setRelationPanelOpen((prev) => !prev)}
                      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium text-violet-600 hover:bg-violet-500/10 dark:text-violet-400"
                      title={locale === "zh" ? "关联管理" : "Relation manager"}
                    >
                      <Network className="h-3.5 w-3.5" />
                      {locale === "zh" ? "关联" : "Link"}
                    </button>
                    {active.platform === "obsidian" ? (
                      <ObsidianWritebackIndicator
                        locale={locale}
                        linkedCount={linkedRelations.length}
                        status={reader?.obsidian_writeback_status ?? active.obsidian_writeback_status ?? null}
                      />
                    ) : null}
                  </div>
                </div>
              </div>

              {isConversation ? (
                <div className="border-b border-border px-4 py-3">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                    {ui("chatWriteUp")}
                  </p>
                  {chatWriteUp ? (
                    <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                      {chatWriteUp}
                    </div>
                  ) : (
                    <p className="text-sm text-muted">{ui("chatWriteUpEmpty")}</p>
                  )}
                </div>
              ) : (!isHotlist || isEconomistHotlist) && !hideAiSummary ? (
                <div className="border-b border-border px-4 py-3">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                    {ui("summary")}
                  </p>
                  <div className="prose prose-sm max-w-none text-foreground prose-p:my-1 prose-p:text-foreground">
                    <ReactMarkdown>{active.summary || ui("noSummary")}</ReactMarkdown>
                  </div>
                </div>
              ) : null}

              <div className="border-b border-border px-4 py-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  {isConversation
                    ? ui("chatTranscript")
                    : isHotlist && !isEconomistHotlist
                      ? ui("hotlistBody")
                      : ui("originalText")}
                </p>
                {isConversation ? (
                  <ConversationTranscriptPanel
                    locale={locale}
                    bodyText={reader?.body_text ?? ""}
                    structured={reader?.telegram_messages}
                    emptyLabel={ui("noReaderText")}
                    expandLabel={ui("expandReader")}
                    collapseLabel={ui("collapseReader")}
                    onExpand={() => {
                      void handleMarkItemRead(active.raw_id);
                      setReaderExpanded(true);
                    }}
                  />
                ) : (
                  <OriginalTextPanel
                    {...originalTextPanelProps}
                    onExpand={
                      isHotlist || isEconomistHotlist
                        ? undefined
                        : () => {
                            void handleMarkItemRead(active.raw_id);
                            setReaderExpanded(true);
                          }
                    }
                  />
                )}
              </div>

              {(!isHotlist || isEconomistHotlist) && active ? (
                <div className="border-b border-border px-4 py-3">
                  <div className="h-52 min-h-[13rem]">
                    <NotesPanel
                      rawId={active.raw_id}
                      title={active.title || active.url}
                      summary={active.summary || ""}
                      bodyText={reader?.body_text ?? ""}
                      translatedBodyText={reader?.translated_body_text}
                      noteHtml={reader?.user_note_html ?? ""}
                      importance={active.importance ?? null}
                      locale={locale}
                      labels={notesPanelLabels}
                      onSaveNote={handleSaveNote}
                      onImportanceChange={handleSaveImportance}
                      onUpload={handleUploadFile}
                    />
                  </div>
                </div>
              ) : null}

              <div className="p-4">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  {ui("tagEdit")}
                </p>
                <TagChipEditor
                  tags={tagList}
                  suggestions={tagSuggestions}
                  locale={locale}
                  onChange={(tags) => void handleTagsChange(tags)}
                />
              </div>

              {canLoadRelated ? (
                <RelatedItemsSection
                  items={relatedItems}
                  locale={locale}
                  titleLabel={ui("relatedReading")}
                  lessRelevantLabel={ui("relatedLessRelevant")}
                  onSelect={(rawId) => {
                    const item = relatedItems.find((row) => row.raw_id === rawId);
                    if (item) {
                      void selectItem(item);
                    }
                  }}
                  onLessRelevant={(toRawId) => void handleRelatedLessRelevant(toRawId)}
                />
              ) : null}
              </div>
            </ColumnScroll>
          ) : (
            <ColumnScroll className="border-r border-border bg-surface p-4">
              <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
                {ui("selectItem")}
              </div>
            </ColumnScroll>
          )}
        </Panel>
        {relationPanelOpen && !isBooks && !isPapers ? (
          <>
            <PanelResizeHandle className="w-px bg-border" />
            <Panel minSize={18} defaultSize={22} className="min-h-0 overflow-hidden">
              <ColumnScroll className="p-3">
                <div className="mb-2 flex items-center gap-2">
                  <h2 className="min-w-0 flex-1 text-xs font-medium uppercase tracking-wider text-muted">
                    {locale === "zh" ? "关联候选" : "Link candidates"}
                  </h2>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium text-violet-600 hover:bg-violet-500/10 dark:text-violet-400"
                    onClick={() => setRelationPanelOpen(false)}
                  >
                    <X className="h-3.5 w-3.5" />
                    {locale === "zh" ? "关闭" : "Close"}
                  </button>
                </div>
                <div className="mb-3 flex items-center gap-2">
                  <div className="on1y-glass-trigger inline-flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md px-2">
                    <Search className="h-4 w-4 text-muted" />
                    <input
                      value={relationQuery}
                      onChange={(event) => setRelationQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                        }
                      }}
                      aria-label={locale === "zh" ? "搜索关联候选" : "Search candidates"}
                      className="w-full bg-transparent text-sm text-foreground outline-none"
                      placeholder={locale === "zh" ? "搜索标题 / 标签 / 正文…" : "Search title / tags / body..."}
                    />
                  </div>
                  {relationSearching ? (
                    <span className="text-xs text-muted">
                      {locale === "zh" ? "搜索中…" : "Searching..."}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    className="inline-flex h-9 items-center gap-1 rounded-md bg-violet-600 px-3 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={selectedRelationCandidateIds.size === 0}
                    onClick={() => void handleConfirmRelationCandidates()}
                  >
                    <Check className="h-3.5 w-3.5" />
                    {locale === "zh"
                      ? `确认关联 (${selectedRelationCandidateIds.size})`
                      : `Link selected (${selectedRelationCandidateIds.size})`}
                  </button>
                </div>
                <p className="mb-2 text-[11px] text-muted">
                  {relationQuery.trim()
                    ? locale === "zh"
                      ? "搜索命中会在标题/摘要中高亮显示"
                      : "Search hits are highlighted in title/summary"
                    : locale === "zh"
                      ? "默认展示推荐系统结果"
                      : "Showing recommendation results by default"}
                </p>
                <div className="space-y-2">
                  {relationCandidateItems.map((item) => (
                    <FeedItemCard
                      key={`rel-${item.raw_id}`}
                      item={item}
                      active={selectedRelationCandidateIds.has(item.raw_id)}
                      locale={locale}
                      themes={themes}
                      compact={false}
                      unknownAuthorLabel={ui("unknownAuthor")}
                      noSummaryLabel={ui("noSummary")}
                      moveThemeLabel={ui("moveTheme")}
                      favoriteLabel={ui("favorite")}
                      unfavoriteLabel={ui("unfavorite")}
                      deleteLabel={ui("deleteItem")}
                      deleteConfirmLabel={ui("deleteConfirm")}
                      batchSelectLabel={ui("batchSelect")}
                      highlightTerm={relationQuery.trim()}
                      authorAvatar={
                        <AuthorAvatar
                          author={item.author}
                          authorAvatar={resolveAuthorAvatar(item.author_avatar)}
                          unknownLabel={ui("unknownAuthor")}
                          size="md"
                        />
                      }
                      selectionMode
                      selected={selectedRelationCandidateIds.has(item.raw_id)}
                      onToggleSelected={() =>
                        setSelectedRelationCandidateIds((prev) => {
                          const next = new Set(prev);
                          if (next.has(item.raw_id)) {
                            next.delete(item.raw_id);
                          } else {
                            next.add(item.raw_id);
                          }
                          return next;
                        })
                      }
                      onSelect={() =>
                        setSelectedRelationCandidateIds((prev) => {
                          const next = new Set(prev);
                          if (next.has(item.raw_id)) {
                            next.delete(item.raw_id);
                          } else {
                            next.add(item.raw_id);
                          }
                          return next;
                        })
                      }
                      onMoveTheme={() => undefined}
                      onToggleFavorite={() => undefined}
                      onDelete={() => undefined}
                    />
                  ))}
                  {relationCandidateItems.length === 0 ? (
                    <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
                      {relationQuery.trim()
                        ? locale === "zh"
                          ? "没有搜索到可关联内容"
                          : "No matching candidate"
                        : locale === "zh"
                          ? "暂无推荐候选"
                          : "No recommended candidate"}
                    </div>
                  ) : null}
                </div>
                {linkedRelations.length > 0 ? (
                  <div className="border-t border-border px-1 py-3">
                    <div className="mb-2 flex items-center justify-between px-1">
                      <p className="text-xs font-medium uppercase tracking-wider text-muted">
                        {locale === "zh" ? "已关联" : "Linked"}
                      </p>
                      <button
                        type="button"
                        className="rounded-md px-2 py-1 text-xs text-muted hover:bg-soft hover:text-foreground disabled:opacity-40"
                        disabled={selectedLinkedIds.size === 0}
                        onClick={() => void handleUnlinkSelected()}
                      >
                        {locale === "zh" ? "取消关联所选" : "Unlink selected"}
                      </button>
                    </div>
                    <div className="space-y-2">
                      {linkedRelationsDisplay.map((row) => (
                        <FeedItemCard
                          key={`linked-${row.item.raw_id}`}
                          item={row.item}
                          active={active?.raw_id === row.item.raw_id}
                          locale={locale}
                          themes={themes}
                          compact={false}
                          unknownAuthorLabel={ui("unknownAuthor")}
                          noSummaryLabel={ui("noSummary")}
                          moveThemeLabel={ui("moveTheme")}
                          favoriteLabel={ui("favorite")}
                          unfavoriteLabel={ui("unfavorite")}
                          deleteLabel={ui("deleteItem")}
                          deleteConfirmLabel={ui("deleteConfirm")}
                          batchSelectLabel={ui("batchSelect")}
                          authorAvatar={
                            <AuthorAvatar
                              author={row.item.author}
                              authorAvatar={resolveAuthorAvatar(row.item.author_avatar)}
                              unknownLabel={ui("unknownAuthor")}
                              size="md"
                            />
                          }
                          selectionMode
                          selected={selectedLinkedIds.has(row.item.raw_id)}
                          onToggleSelected={() =>
                            setSelectedLinkedIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(row.item.raw_id)) {
                                next.delete(row.item.raw_id);
                              } else {
                                next.add(row.item.raw_id);
                              }
                              return next;
                            })
                          }
                          onSelect={() => void selectItem(row.item)}
                          onMoveTheme={() => undefined}
                          onToggleFavorite={() => undefined}
                          onDelete={() => undefined}
                        />
                      ))}
                    </div>
                  </div>
                ) : null}
              </ColumnScroll>
            </Panel>
          </>
        ) : null}
        </PanelGroup>
      )}
    </div>
    <ColdStartFloatingPanel locale={locale} status={coldStartStatus} />
    <FirstRunGuide
      locale={locale}
      open={coldStartOnboardingOpen}
      onClose={() => setColdStartOnboardingOpen(false)}
      onStartSync={() => {
        setColdStartOnboardingOpen(false);
        void startColdStartJob();
      }}
    />
    </>
  );
}

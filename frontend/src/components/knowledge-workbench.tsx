"use client";

import * as Select from "@radix-ui/react-select";
import {
  BarChart3,
  CheckSquare,
  ChevronDown,
  ExternalLink,
  Flame,
  Forward,
  Inbox,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Star,
  Trash2,
  X
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { ColdStartFloatingPanel } from "@/components/cold-start-floating-panel";
import { AppUpdateBanner } from "@/components/app-update-banner";
import { PipelineAlertsBanner } from "@/components/pipeline-alerts-banner";
import { FirstRunGuide } from "@/components/first-run-guide";
import { FeedItemCard } from "@/components/feed-item-card";
import { ThemeMovePopover } from "@/components/theme-move-popover";
import { NotesPanel } from "@/components/notes-panel";
import { OriginalTextPanel } from "@/components/original-text-panel";
import { ContentTypeIndicator } from "@/components/content-type-indicator";
import { RelatedItemsSection } from "@/components/related-items-section";
import { AccountMenu } from "@/components/account-menu";
import { TagChipEditor } from "@/components/tag-chip-editor";
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
  runHotlistSync,
  getCollectionCounts,
  getCookieStatuses,
  getCreators,
  getFullSyncStatus,
  runFullSync,
  type FullSyncStatus,
  economistEpubDownloadUrl,
  getEconomistWeeks,
  getKnowledgeItems,
  getStatsOverview,
  type EconomistWeekOption,
  type HotlistSource,
  getReaderContent,
  getRelatedItems,
  markItemRead,
  patchItemRead,
  postRelatedLessRelevant,
  getTaxonomy,
  moveItemTheme,
  patchItemClassification,
  saveItemNote,
  restoreKnowledgeItem,
  toggleItemFavorite,
  translateItemTranscript,
  uploadDocument
} from "@/lib/api";
import { handleExternalLinkClick } from "@/lib/open-external";
import { t, type UiKey } from "@/lib/i18n";
import { platformLabel } from "@/lib/platform-label";
import {
  type CreatorRow,
  type DynamicTagRow,
  type KnowledgeItem,
  type ReaderContent,
  type ThemeRow
} from "@/lib/types";
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
  const isUnread = collection === "unread";
  const isFeedBrowse = !isTrash && !isFavorites && !isHotlist && !isUnread;

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
  }>({
    favorites: 0,
    trash: 0,
    hotlist: 0,
    unread: 0
  });
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
    () => sortOptionsForUi(locale, hasSearch, collection),
    [locale, hasSearch, collection]
  );

  const displayItems = useMemo(
    () =>
      isHotlist
        ? items
        : sortKnowledgeItems(items, sortMode, locale, { hasSearch }),
    [items, sortMode, locale, hasSearch, isHotlist]
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
  }, [active?.raw_id, active?.summary, active?.distill_status, canLoadRelated]);

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

  function buildItemsQuery(offset: number, limit = FEED_BATCH_SIZE) {
    return {
      locale,
      themeId: isHotlist ? undefined : selectedThemeId,
      creatorKey: isHotlist ? undefined : selectedCreatorKey,
      tagId: isHotlist ? undefined : selectedTagId,
      q: isHotlist ? undefined : query,
      platform: isHotlist ? undefined : filterValue(platform),
      collection: (isFeedBrowse ? "feed" : collection) as KnowledgeCollection,
      hotlistDate: isHotlist ? hotlistDate : undefined,
      hotlistSource: isHotlist ? hotlistSource : undefined,
      feedDate: isFeedBrowse && feedDate ? feedDate : undefined,
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
    setItems((prev) => prev.map((row) => (row.raw_id === rawId ? patch(row) : row)));
    setActive((prev) => (prev?.raw_id === rawId ? patch(prev) : prev));
    setCollectionCounts((prev) => ({
      ...prev,
      unread: readAt
        ? Math.max(0, prev.unread - 1)
        : prev.unread +
          (items.some((row) => row.raw_id === rawId && !row.read_at) || isUnread ? 0 : 1)
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
    feedDate
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
    feedDate
  ]);

  async function selectItem(item: KnowledgeItem): Promise<void> {
    setReaderExpanded(false);
    setActive(item);
    setTagList(item.tags.map((tg) => tg.name));
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
    if (next !== "feed") {
      setFeedDate(null);
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
    setReader((prev) => (prev ? { ...prev, user_note_html: html } : prev));
    setMessage(ui("saveNote"));
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

  const tagSuggestions = useMemo(
    () => dynamicTags.map((tag) => tag.name),
    [dynamicTags]
  );

  const notesPanelLabels = {
    notes: ui("notes"),
    notesPlaceholder: ui("notesPlaceholder"),
    saveNote: ui("saveNote"),
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
            <AccountMenu locale={locale} onLocaleChange={applyLocale} onMessage={setMessage} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="on1y-glass-trigger inline-flex items-center gap-2 rounded-md px-2 py-1.5">
            <Search className="h-4 w-4 text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={ui("searchPlaceholder")}
              className="w-56 bg-transparent text-sm text-foreground outline-none"
            />
          </div>
          {query.trim() && searchTotal !== undefined ? (
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
              <OriginalTextPanel
                {...originalTextPanelProps}
                expanded
                onCollapse={() => setReaderExpanded(false)}
              />
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
                locale={locale}
                labels={notesPanelLabels}
                onSaveNote={handleSaveNote}
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
                labels={{
                  themes: ui("themes"),
                  allThemes: ui("allThemes"),
                  addTheme: ui("addTheme"),
                  themeName: ui("themeName"),
                  themeDesc: ui("themeDesc"),
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
                    onClick={() => switchCollection("unread")}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                      isUnread
                    )}`}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Inbox className="h-3.5 w-3.5" />
                      {ui("collectionUnread")}
                    </span>
                    <span className={`text-xs ${isUnread ? GLASS_MUTED : "text-muted"}`}>
                      {collectionCounts.unread}
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
                      : isUnread
                        ? ui("collectionUnread")
                      : isTrash
                        ? ui("collectionTrash")
                        : isHotlist
                          ? ui("collectionHotlist")
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
                          : isUnread
                            ? ui("unreadEmpty")
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
        </Panel>

        <PanelResizeHandle className="w-px bg-border" />

        <Panel minSize={22} defaultSize={58} className="min-h-0 overflow-hidden">
          {active ? (
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
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-xs text-muted">{ui("sourcePlatform")}</span>
                    <span className="rounded bg-soft px-2 py-0.5 text-xs font-medium text-foreground">
                      {platformLabel(active.platform, locale)}
                    </span>
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
                    {active.is_read || active.read_at ? (
                      <button
                        type="button"
                        onClick={() => void handleMarkUnread()}
                        className="text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {ui("markUnread")}
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>

              {!isHotlist || isEconomistHotlist ? (
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
                  {isHotlist && !isEconomistHotlist
                    ? ui("hotlistBody")
                    : ui("originalText")}
                </p>
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
              </div>

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

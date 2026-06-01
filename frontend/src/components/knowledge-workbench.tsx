"use client";

import * as Select from "@radix-ui/react-select";
import { ChevronDown, ExternalLink, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { FeedItemCard } from "@/components/feed-item-card";
import { NotesPanel } from "@/components/notes-panel";
import { OriginalTextPanel } from "@/components/original-text-panel";
import { SubscriptionSettingsButton } from "@/components/subscription-settings-panel";
import { TagChipEditor } from "@/components/tag-chip-editor";
import {
  createTheme,
  deleteKnowledgeItem,
  getKnowledgeItems,
  getReaderContent,
  getTaxonomy,
  moveItemTheme,
  patchItemClassification,
  saveItemNote,
  splitTheme,
  toggleItemFavorite,
  translateItemTranscript,
  uploadDocument
} from "@/lib/api";
import { t, themeDisplayName, type UiKey } from "@/lib/i18n";
import { platformLabel } from "@/lib/platform-label";
import {
  type DynamicTagRow,
  type KnowledgeItem,
  type ReaderContent,
  type ThemeRow
} from "@/lib/types";
import { ALL_FILTER, useKnowledgeFilterStore } from "@/store/knowledge-store";

function filterValue(value: string): string | undefined {
  return value === ALL_FILTER || value === "" ? undefined : value;
}


function parseSplitLines(raw: string): Array<{ name_zh: string; description_zh: string }> {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, ...rest] = line.split("|");
      return {
        name_zh: (name ?? "").trim(),
        description_zh: rest.join("|").trim()
      };
    })
    .filter((row) => row.name_zh);
}

function FilterSelect(props: {
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ label: string; value: string }>;
}): JSX.Element {
  return (
    <Select.Root value={props.value || ALL_FILTER} onValueChange={props.onChange}>
      <Select.Trigger className="inline-flex h-9 min-w-[7rem] items-center justify-between gap-2 rounded-md border border-border bg-white px-3 text-sm text-black">
        <Select.Value placeholder={props.placeholder} />
        <Select.Icon>
          <ChevronDown className="h-4 w-4 text-muted" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="z-50 overflow-hidden rounded-md border border-border bg-white shadow-lg">
          <Select.Viewport className="p-1">
            {props.options.map((opt) => (
              <Select.Item
                key={opt.value}
                value={opt.value}
                className="cursor-pointer rounded px-2 py-1.5 text-sm text-black outline-none data-[highlighted]:bg-soft"
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

function ColumnScroll(props: { children: React.ReactNode; className?: string }): JSX.Element {
  return (
    <div className={`h-full min-h-0 overflow-y-auto scrollbar-thin ${props.className ?? ""}`}>
      {props.children}
    </div>
  );
}

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
        className={`${sizeClass} shrink-0 rounded-full object-cover bg-neutral-200`}
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <div
      className={`${sizeClass} flex shrink-0 items-center justify-center rounded-full bg-neutral-200 font-medium text-neutral-600`}
    >
      {name.slice(0, 1).toUpperCase()}
    </div>
  );
}

export default function KnowledgeWorkbench(): JSX.Element {
  const {
    locale,
    selectedThemeId,
    selectedTagId,
    query,
    platform,
    source,
    setLocale,
    setTheme,
    setTag,
    setQuery,
    setPlatform,
    setSource
  } = useKnowledgeFilterStore();

  const ui = (key: UiKey): string => t(locale, key);

  const [themes, setThemes] = useState<ThemeRow[]>([]);
  const [dynamicTags, setDynamicTags] = useState<DynamicTagRow[]>([]);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [active, setActive] = useState<KnowledgeItem | undefined>(undefined);
  const [reader, setReader] = useState<ReaderContent | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(false);
  const [message, setMessage] = useState<string>("");
  const [tagList, setTagList] = useState<string[]>([]);
  const [showThemeManager, setShowThemeManager] = useState<boolean>(false);
  const [newThemeName, setNewThemeName] = useState<string>("");
  const [newThemeDesc, setNewThemeDesc] = useState<string>("");
  const [splitSourceId, setSplitSourceId] = useState<string>("");
  const [splitLines, setSplitLines] = useState<string>("");
  const [readerExpanded, setReaderExpanded] = useState<boolean>(false);
  const [searchTotal, setSearchTotal] = useState<number | undefined>(undefined);
  const [searchEngine, setSearchEngine] = useState<string | undefined>(undefined);

  const platformOptions = useMemo(
    () => [
      { label: locale === "zh" ? "所有平台" : "All platforms", value: ALL_FILTER },
      { label: "知乎", value: "zhihu" },
      { label: "YouTube", value: "youtube" },
      { label: locale === "zh" ? "上传" : "Upload", value: "upload" },
      { label: locale === "zh" ? "手动" : "Manual", value: "manual" }
    ],
    [locale]
  );

  const sourceOptions = useMemo(
    () => [
      { label: locale === "zh" ? "所有来源" : "All sources", value: ALL_FILTER },
      { label: "rss", value: "rss" },
      { label: "manual", value: "manual" },
      { label: "youtube_feed", value: "youtube_feed" }
    ],
    [locale]
  );


  async function loadReader(rawId: number): Promise<void> {
    try {
      const content = await getReaderContent(rawId);
      setReader(content);
    } catch {
      setReader(undefined);
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

  async function refreshData(): Promise<void> {
    setLoading(true);
    setMessage("");
    try {
      const [taxonomy, itemResp] = await Promise.all([
        getTaxonomy(locale),
        getKnowledgeItems({
          locale,
          themeId: selectedThemeId,
          tagId: selectedTagId,
          q: query,
          platform: filterValue(platform),
          source: filterValue(source),
          limit: 80
        })
      ]);
      setThemes(taxonomy.themes);
      setDynamicTags(taxonomy.tags);
      setItems(itemResp.items);
      setSearchTotal(itemResp.total);
      setSearchEngine(itemResp.engine);
      if (itemResp.items.length > 0) {
        const stillExists = itemResp.items.find((x) => x.raw_id === active?.raw_id);
        const next = stillExists ?? itemResp.items[0];
        setActive(next);
        setTagList(next.tags.map((tg) => tg.name));
        await loadReader(next.raw_id);
      } else {
        setActive(undefined);
        setReader(undefined);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const delay = query.trim() ? 300 : 0;
    const timer = window.setTimeout(() => {
      if (!cancelled) {
        void refreshData();
      }
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, selectedThemeId, selectedTagId, platform, source, query]);

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
    try {
      await toggleItemFavorite(item.raw_id, !item.starred);
      setItems((prev) =>
        prev.map((row) =>
          row.raw_id === item.raw_id ? { ...row, starred: !item.starred } : row
        )
      );
      if (active?.raw_id === item.raw_id) {
        setActive({ ...item, starred: !item.starred });
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "favorite failed");
    }
  }

  async function handleDeleteItem(rawId: number): Promise<void> {
    try {
      await deleteKnowledgeItem(rawId);
      setMessage(locale === "zh" ? "已删除" : "Deleted");
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "delete failed");
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

  async function handleAddTheme(): Promise<void> {
    if (!newThemeName.trim()) {
      return;
    }
    try {
      await createTheme({
        name_zh: newThemeName.trim(),
        name_en: newThemeName.trim(),
        description_zh: newThemeDesc.trim(),
        description_en: newThemeDesc.trim()
      });
      setNewThemeName("");
      setNewThemeDesc("");
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "create theme failed");
    }
  }

  async function handleSplitTheme(): Promise<void> {
    const sourceId = Number(splitSourceId);
    const targets = parseSplitLines(splitLines);
    if (!sourceId || targets.length === 0) {
      return;
    }
    setLoading(true);
    try {
      const result = await splitTheme({
        source_theme_id: sourceId,
        new_themes: targets,
        archive_source: true
      });
      setMessage(`${ui("splitDone")}: ${result.remapped}`);
      setSplitLines("");
      await refreshData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "split failed");
    } finally {
      setLoading(false);
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
    upload: ui("upload"),
    chooseFile: ui("chooseFile"),
    uploadClassify: ui("uploadClassify"),
    exportWord: ui("exportWord"),
    exportPdf: ui("exportPdf"),
    summary: ui("summary"),
    originalText: ui("originalText")
  };

  return (
    <div className="flex h-screen w-full flex-col bg-white text-black">
      <div className="shrink-0 border-b border-border bg-white px-4 py-3">
        <div className="mb-2 flex items-center justify-between">
          <h1 className="text-lg font-semibold tracking-tight">{ui("appTitle")}</h1>
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
              <button
                type="button"
                onClick={() => setLocale("zh")}
                className={`px-2.5 py-1.5 ${locale === "zh" ? "bg-black text-white" : "bg-white"}`}
              >
                {ui("langZh")}
              </button>
              <button
                type="button"
                onClick={() => setLocale("en")}
                className={`px-2.5 py-1.5 ${locale === "en" ? "bg-black text-white" : "bg-white"}`}
              >
                {ui("langEn")}
              </button>
            </div>
            <SubscriptionSettingsButton locale={locale} onMessage={setMessage} />
            <button
              type="button"
              onClick={() => void refreshData()}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-3 py-1.5 text-sm hover:bg-soft"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {ui("refresh")}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-2 py-1.5">
            <Search className="h-4 w-4 text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={ui("searchPlaceholder")}
              className="w-56 bg-transparent text-sm text-black outline-none placeholder:text-neutral-400"
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
          <FilterSelect
            placeholder={ui("source")}
            value={source}
            onChange={setSource}
            options={sourceOptions}
          />
          <button
            type="button"
            onClick={() => void refreshData()}
            className="rounded-md border border-black bg-black px-3 py-1.5 text-sm text-white hover:bg-neutral-800"
          >
            {ui("filter")}
          </button>
          {message ? <span className="text-sm text-muted">{message}</span> : null}
        </div>
      </div>

      {readerExpanded && active ? (
        <PanelGroup key="reader-expanded" direction="horizontal" className="min-h-0 flex-1">
          <Panel minSize={25} defaultSize={58} className="min-h-0 overflow-hidden">
            <div className="flex h-full min-h-0 flex-col border-r border-border bg-white p-4">
              <div className="mb-3 shrink-0">
                <h3 className="text-lg font-semibold leading-snug">{active.title || "—"}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>{platformLabel(active.platform, locale)}</span>
                  <a
                    href={active.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 hover:text-black hover:underline"
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
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                {ui("themes")}
              </h2>
              <div className="mb-4 space-y-0.5">
                <button
                  type="button"
                  onClick={() => setTheme(undefined)}
                  className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                    selectedThemeId === undefined
                      ? "bg-black font-medium text-white"
                      : "hover:bg-soft"
                  }`}
                >
                  {ui("allThemes")}
                </button>
                {themes.map((theme) => (
                  <button
                    key={theme.id}
                    type="button"
                    onClick={() => setTheme(theme.id)}
                    className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${
                      selectedThemeId === theme.id
                        ? "bg-black font-medium text-white"
                        : "hover:bg-soft"
                    }`}
                  >
                    <span>{themeDisplayName(theme, locale)}</span>
                    <span
                      className={`text-xs ${
                        selectedThemeId === theme.id ? "text-neutral-300" : "text-muted"
                      }`}
                    >
                      {theme.item_count}
                    </span>
                  </button>
                ))}
              </div>

              <button
                type="button"
                onClick={() => setShowThemeManager((v) => !v)}
                className="mb-2 w-full rounded border border-border px-2 py-1.5 text-left text-xs hover:bg-soft"
              >
                {ui("manageThemes")} {showThemeManager ? "▾" : "▸"}
              </button>
              {showThemeManager ? (
                <div className="mb-4 space-y-2 rounded border border-border bg-panel p-2">
                  <p className="text-xs font-medium text-muted">{ui("addTheme")}</p>
                  <input
                    value={newThemeName}
                    onChange={(e) => setNewThemeName(e.target.value)}
                    placeholder={ui("themeName")}
                    className="w-full rounded border border-border bg-white px-2 py-1 text-xs"
                  />
                  <input
                    value={newThemeDesc}
                    onChange={(e) => setNewThemeDesc(e.target.value)}
                    placeholder={ui("themeDesc")}
                    className="w-full rounded border border-border bg-white px-2 py-1 text-xs"
                  />
                  <button
                    type="button"
                    onClick={() => void handleAddTheme()}
                    className="w-full rounded border border-black bg-black py-1 text-xs text-white"
                  >
                    {ui("addTheme")}
                  </button>
                  <p className="pt-1 text-xs font-medium text-muted">{ui("splitTheme")}</p>
                  <select
                    value={splitSourceId}
                    onChange={(e) => setSplitSourceId(e.target.value)}
                    className="w-full rounded border border-border bg-white px-2 py-1 text-xs"
                  >
                    <option value="">{ui("splitSource")}</option>
                    {themes.map((th) => (
                      <option key={th.id} value={String(th.id)}>
                        {themeDisplayName(th, locale)} ({th.item_count})
                      </option>
                    ))}
                  </select>
                  <textarea
                    value={splitLines}
                    onChange={(e) => setSplitLines(e.target.value)}
                    placeholder={ui("splitExample")}
                    className="h-20 w-full rounded border border-border bg-white px-2 py-1 text-xs"
                  />
                  <button
                    type="button"
                    onClick={() => void handleSplitTheme()}
                    className="w-full rounded border border-neutral-600 py-1 text-xs hover:bg-soft"
                  >
                    {ui("runSplit")}
                  </button>
                </div>
              ) : null}

              <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                {ui("tags")}
              </h2>
              <div className="space-y-0.5">
                <button
                  type="button"
                  onClick={() => setTag(undefined)}
                  className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                    selectedTagId === undefined ? "bg-neutral-100 font-medium" : "hover:bg-soft"
                  }`}
                >
                  {ui("allTags")}
                </button>
                {dynamicTags.map((tag) => (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => setTag(tag.id)}
                    className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${
                      selectedTagId === tag.id ? "bg-neutral-100 font-medium" : "hover:bg-soft"
                    }`}
                  >
                    <span className="truncate">#{tag.name}</span>
                    <span className="ml-2 shrink-0 text-xs text-muted">{tag.item_count}</span>
                  </button>
                ))}
              </div>
          </ColumnScroll>
        </Panel>

        <PanelResizeHandle className="w-px bg-border" />

        <Panel minSize={20} defaultSize={24} className="min-h-0 overflow-hidden">
          <ColumnScroll className="border-r border-border p-3">
              <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted">
                {ui("feed")} ({items.length})
              </h2>
              <div className="space-y-2">
                {items.map((item) => (
                  <FeedItemCard
                    key={item.raw_id}
                    item={item}
                    active={active?.raw_id === item.raw_id}
                    locale={locale}
                    themes={themes}
                    unknownAuthorLabel={ui("unknownAuthor")}
                    noSummaryLabel={ui("noSummary")}
                    moveThemeLabel={ui("moveTheme")}
                    favoriteLabel={ui("favorite")}
                    unfavoriteLabel={ui("unfavorite")}
                    deleteLabel={ui("deleteItem")}
                    deleteConfirmLabel={ui("deleteConfirm")}
                    authorAvatar={
                      <AuthorAvatar
                        author={item.author}
                        authorAvatar={resolveAuthorAvatar(item.author_avatar)}
                        unknownLabel={ui("unknownAuthor")}
                        size="md"
                      />
                    }
                    onSelect={() => void selectItem(item)}
                    onMoveTheme={(themeId) => void handleThemeMoveForItem(item.raw_id, themeId)}
                    onToggleFavorite={() => void handleToggleFavorite(item)}
                    onDelete={() => void handleDeleteItem(item.raw_id)}
                  />
                ))}
                {items.length === 0 ? (
                  <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
                    {ui("noItems")}
                  </div>
                ) : null}
              </div>
          </ColumnScroll>
        </Panel>

        <PanelResizeHandle className="w-px bg-border" />

        <Panel minSize={22} defaultSize={58} className="min-h-0 overflow-hidden">
          {active ? (
            <ColumnScroll className="border-r border-border bg-white">
              <div className="space-y-0">
              <div className="space-y-3 border-b border-border p-4">
                {(() => {
                  const cover = resolveCover({
                    cover_image: reader?.cover_image ?? active.cover_image,
                    author_avatar: reader?.author_avatar ?? active.author_avatar
                  });
                  return cover ? (
                    <a
                      href={active.url}
                      target="_blank"
                      rel="noreferrer"
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
                })()}
                <div>
                  <h3 className="text-base font-semibold leading-snug">{active.title || "—"}</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-xs text-muted">{ui("sourcePlatform")}</span>
                    <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs font-medium">
                      {platformLabel(active.platform, locale)}
                    </span>
                    <a
                      href={active.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-neutral-700 underline-offset-2 hover:text-black hover:underline"
                    >
                      {ui("openLink")}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                </div>
              </div>

              <div className="border-b border-border px-4 py-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  {ui("summary")}
                </p>
                <div className="prose prose-sm max-w-none text-black prose-p:my-1 prose-p:text-neutral-800">
                  <ReactMarkdown>{active.summary || ui("noSummary")}</ReactMarkdown>
                </div>
              </div>

              <div className="border-b border-border px-4 py-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
                  {ui("originalText")}
                </p>
                <OriginalTextPanel
                  {...originalTextPanelProps}
                  onExpand={() => setReaderExpanded(true)}
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
              </div>
            </ColumnScroll>
          ) : (
            <ColumnScroll className="border-r border-border bg-white p-4">
              <div className="rounded border border-dashed border-border p-4 text-sm text-muted">
                {ui("selectItem")}
              </div>
            </ColumnScroll>
          )}
        </Panel>
        </PanelGroup>
      )}
    </div>
  );
}

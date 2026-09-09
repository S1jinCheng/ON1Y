"use client";

import {
  ExternalLink,
  FileText,
  Loader2,
  Plus,
  Search,
  Star,
  Trash2,
  Upload
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ImportanceStars } from "@/components/importance-stars";
import { RelatedItemsSection } from "@/components/related-items-section";
import { RichNoteEditor } from "@/components/rich-note-editor";
import { TagChipEditor } from "@/components/tag-chip-editor";
import {
  createPaper,
  deletePaper,
  fetchRelatedPapers,
  fetchPaperSettings,
  getTaxonomy,
  listPapers,
  openLocalPath,
  postRelatedLessRelevant,
  updatePaper,
  uploadPaperFile
} from "@/lib/api";
import { openZoteroPdf } from "@/lib/open-external";
import { openPdfWithApplication } from "@/lib/pdf-application";
import type { PaperItem, PaperSettings, PaperStatus } from "@/lib/paper-types";
import type { KnowledgeItem, Locale } from "@/lib/types";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

function statusLabel(locale: Locale, status: PaperStatus): string {
  if (status === "to_read") return L(locale, "待读", "To read");
  if (status === "reading") return L(locale, "在读", "Reading");
  return L(locale, "已读", "Read");
}

const STATUSES: PaperStatus[] = ["to_read", "reading", "read"];

async function openPaperDocument(
  item: PaperItem,
  locale: Locale,
  onMessage: (message: string) => void
): Promise<void> {
  let settings: PaperSettings | null = null;
  try {
    settings = await fetchPaperSettings();
  } catch {
    // Preserve the previous Zotero-first behavior if settings cannot be loaded.
  }

  const mode = settings?.pdf_open_mode ?? "zotero";
  if (mode === "zotero" && item.zotero_reader_url) {
    try {
      await openZoteroPdf(item.zotero_reader_url);
      return;
    } catch (error) {
      if (!item.pdf_path) {
        onMessage(error instanceof Error ? error.message : "open Zotero failed");
        return;
      }
    }
  }

  if (item.pdf_path) {
    if (mode === "custom") {
      try {
        const applicationPath = settings?.pdf_application_path?.trim();
        if (!applicationPath) {
          throw new Error(L(locale, "请先在设置中选择 PDF 阅读应用", "Choose a PDF application in Settings first"));
        }
        await openPdfWithApplication(applicationPath, item.pdf_path);
        return;
      } catch (error) {
        try {
          await openLocalPath(item.pdf_path);
          onMessage(L(locale, "指定应用不可用，已使用系统默认阅读器", "Custom app unavailable; opened with the system reader"));
          return;
        } catch {
          onMessage(error instanceof Error ? error.message : "open PDF failed");
          return;
        }
      }
    }
    try {
      await openLocalPath(item.pdf_path);
      return;
    } catch (error) {
      if (!item.zotero_reader_url) {
        onMessage(error instanceof Error ? error.message : "open PDF failed");
        return;
      }
    }
  }

  if (item.zotero_reader_url) {
    try {
      await openZoteroPdf(item.zotero_reader_url);
      return;
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "open Zotero failed");
      return;
    }
  }
  onMessage(L(locale, "这篇 Paper 没有可打开的 PDF", "This paper has no PDF to open"));
}

type ListProps = {
  locale: Locale;
  activeId: number | null;
  refreshKey: number;
  onSelect: (item: PaperItem) => void;
  onStartManualAdd: () => void;
  onChanged: () => void;
  onRemoved: (id: number) => void;
  onMessage: (message: string) => void;
};

export function PapersListColumn(props: ListProps): JSX.Element {
  const { locale, activeId, refreshKey, onSelect, onStartManualAdd, onChanged, onRemoved, onMessage } = props;
  const [items, setItems] = useState<PaperItem[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<PaperStatus | "all">("all");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listPapers({ status: status === "all" ? undefined : status, query: query.trim() || undefined });
      setItems(response.items);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "load papers failed");
    } finally {
      setLoading(false);
    }
  }, [onMessage, query, status]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), query ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [query, refresh, refreshKey]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2 border-b border-border pb-3">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            title={L(locale, "手动新建 Paper", "Create paper")}
            onClick={onStartManualAdd}
            className="inline-flex items-center justify-center rounded-md border border-border p-1.5 hover:bg-soft"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>        <div className="flex gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-1 rounded-md border border-border px-2 py-1">
            <Search className="h-3.5 w-3.5 text-muted" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={L(locale, "搜索标题、作者、DOI…", "Title, author, DOI…")} className="min-w-0 flex-1 bg-transparent text-xs outline-none" />
          </label>
          <select value={status} onChange={(event) => setStatus(event.target.value as PaperStatus | "all")} className="rounded-md border border-border bg-surface px-1 text-xs">
            <option value="all">{L(locale, "全部", "All")}</option>
            {STATUSES.map((value) => <option key={value} value={value}>{statusLabel(locale, value)}</option>)}
          </select>
        </div>
      </div>


      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pt-3">
        {loading && !items.length ? <div className="flex items-center gap-2 text-xs text-muted"><Loader2 className="h-4 w-4 animate-spin" />{L(locale, "加载中…", "Loading…")}</div> : null}
        {items.map((item) => {
          const starred = (item.importance ?? 0) > 0;
          return (
            <div key={item.id} className={`group flex rounded-lg border ${activeId === item.id ? "border-foreground bg-soft" : "border-border bg-surface hover:bg-panel"}`}>
              <button type="button" onClick={() => onSelect(item)} className="min-w-0 flex-1 p-3 text-left">
                <p className="line-clamp-2 text-sm font-medium leading-snug">{item.title}</p>
                <p className="mt-1 line-clamp-1 text-xs text-muted">{item.authors.map((author) => author.name).join(", ") || L(locale, "作者未知", "Unknown authors")}</p>
                <div className="mt-2 flex flex-wrap gap-1 text-[10px] text-muted"><span className="rounded bg-soft px-1.5 py-0.5">{statusLabel(locale, item.status)}</span>{item.year ? <span className="rounded bg-soft px-1.5 py-0.5">{item.year}</span> : null}{item.zotero_key ? <span className="rounded bg-soft px-1.5 py-0.5">Zotero</span> : null}{item.pdf_path ? <span className="rounded bg-soft px-1.5 py-0.5">PDF</span> : null}</div>
              </button>
              <div className="flex w-9 shrink-0 flex-col items-center justify-center border-l border-border">
                <button type="button" title={starred ? L(locale, "取消收藏", "Unfavorite") : L(locale, "收藏", "Favorite")} onClick={() => void updatePaper(item.id, { importance: starred ? null : 4 }).then(() => { void refresh(); onChanged(); })} className="p-2 text-muted hover:text-foreground"><Star className={`h-4 w-4 ${starred ? "fill-amber-400 text-amber-500" : ""}`} /></button>
                {item.zotero_reader_url || item.pdf_path ? <button type="button" title={L(locale, "打开 PDF", "Open PDF")} onClick={() => void openPaperDocument(item, locale, onMessage)} className="p-2 text-muted hover:text-foreground"><FileText className="h-4 w-4" /></button> : null}
                <button type="button" title={L(locale, "删除", "Delete")} onClick={() => void deletePaper(item.id).then(() => { setItems((rows) => rows.filter((row) => row.id !== item.id)); onRemoved(item.id); })} className="p-2 text-muted hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
              </div>
            </div>
          );
        })}
        {!loading && !items.length ? <div className="rounded border border-dashed border-border p-4 text-sm text-muted">{L(locale, "还没有 Paper。点击左上角 + 手动新建，可在表单中附加 PDF。", "No papers yet. Use + to create one and attach a PDF in the form.")}</div> : null}
      </div>
    </div>
  );
}

type DetailProps = {
  locale: Locale;
  item: PaperItem | null;
  manualAdd: boolean;
  onSaved: (item: PaperItem) => void;
  onCancelManual: () => void;
  onSelectPaper: (id: number) => void;
  onSelectKnowledgeItem: (item: KnowledgeItem) => void;
  onMessage: (message: string) => void;
};

export function PapersDetailColumn(props: DetailProps): JSX.Element {
  const { locale, item, manualAdd, onSaved, onCancelManual, onSelectPaper, onSelectKnowledgeItem, onMessage } = props;
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [abstract, setAbstract] = useState("");
  const [venue, setVenue] = useState("");
  const [year, setYear] = useState("");
  const [doi, setDoi] = useState("");
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<PaperStatus>("to_read");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [tags, setTags] = useState<string[]>(item?.tags ?? []);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [related, setRelated] = useState<KnowledgeItem[]>([]);

  useEffect(() => setTags(item?.tags ?? []), [item?.id, item?.tags]);
  useEffect(() => { void getTaxonomy(locale).then((value) => setTagSuggestions(value.tags.map((row) => row.name))).catch(() => undefined); }, [locale]);
  const itemId = item?.id;
  const itemTagsKey = (item?.tags ?? []).join("\0");
  useEffect(() => {
    if (!itemId) { setRelated([]); return; }
    void fetchRelatedPapers(itemId).then((value) => setRelated(value.items)).catch(() => setRelated([]));
  }, [itemId, itemTagsKey]);

  async function submitNew(): Promise<void> {
    if (!title.trim() && !file) return;
    setSaving(true);
    try {
      const names = authors.replace("；", ";").split(";").map((name) => name.trim()).filter(Boolean);
      const created = file
        ? (await uploadPaperFile(file, { title, authors, status })).paper
        : await createPaper({ title, authors: names.map((name) => ({ name })), abstract, venue, year: year ? Number(year) : undefined, doi, url, status });
      onSaved(created);
      onMessage(L(locale, "Paper 已保存", "Paper saved"));
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  if (manualAdd) {
    return <div className="h-full overflow-y-auto p-4"><h2 className="mb-4 text-lg font-semibold">{L(locale, "新建 Paper", "New paper")}</h2><div className="max-w-2xl space-y-3 text-sm">
      <label className="block"><span className="text-xs text-muted">{L(locale, "标题", "Title")}</span><input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label>
      <label className="block"><span className="text-xs text-muted">{L(locale, "作者（用分号分隔）", "Authors (semicolon separated)")}</span><input value={authors} onChange={(e) => setAuthors(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label>
      <div className="grid grid-cols-2 gap-3"><label><span className="text-xs text-muted">{L(locale, "期刊 / 会议", "Venue")}</span><input value={venue} onChange={(e) => setVenue(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label><label><span className="text-xs text-muted">{L(locale, "年份", "Year")}</span><input inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label></div>
      <div className="grid grid-cols-2 gap-3"><label><span className="text-xs text-muted">DOI</span><input value={doi} onChange={(e) => setDoi(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label><label><span className="text-xs text-muted">URL</span><input value={url} onChange={(e) => setUrl(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label></div>
      <label className="block"><span className="text-xs text-muted">{L(locale, "摘要", "Abstract")}</span><textarea value={abstract} onChange={(e) => setAbstract(e.target.value)} rows={7} className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2" /></label>
      <div className="flex flex-wrap items-center gap-3"><select value={status} onChange={(e) => setStatus(e.target.value as PaperStatus)} className="rounded-md border border-border bg-surface px-2 py-1.5">{STATUSES.map((value) => <option key={value} value={value}>{statusLabel(locale, value)}</option>)}</select><label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-1.5 hover:bg-soft"><Upload className="h-4 w-4" />{file?.name ?? L(locale, "附加 PDF（可选）", "Attach PDF (optional)")}<input type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label></div>
      <div className="flex gap-2"><button type="button" disabled={saving || (!title.trim() && !file)} onClick={() => void submitNew()} className="rounded-md bg-inverse px-4 py-2 text-inverse-foreground disabled:opacity-50">{saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}</button><button type="button" onClick={onCancelManual} className="rounded-md border border-border px-4 py-2">{L(locale, "取消", "Cancel")}</button></div>
    </div></div>;
  }

  if (!item) return <div className="flex h-full items-center justify-center p-8 text-sm text-muted"><div className="text-center"><FileText className="mx-auto mb-3 h-10 w-10 opacity-50" />{L(locale, "选择一篇 Paper 查看详情", "Select a paper to view details")}</div></div>;

  async function patch(input: Parameters<typeof updatePaper>[1]): Promise<void> {
    try { onSaved(await updatePaper(item!.id, input)); } catch (error) { onMessage(error instanceof Error ? error.message : "update failed"); }
  }

  function handleRelatedSelect(rawId: number): void {
    const row = related.find((value) => value.raw_id === rawId);
    if (!row) return;
    const match = row.url.match(/^on1y:\/\/papers\/(\d+)$/);
    if (match) onSelectPaper(Number(match[1])); else onSelectKnowledgeItem(row);
  }

  return <div className="h-full overflow-y-auto p-4"><div className="mx-auto max-w-3xl space-y-5">
    <div><div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-semibold leading-snug">{item.title}</h2><div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-sm">{item.authors.map((author, index) => <span key={`${author.name}-${index}`}><a href={author.google_scholar_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{author.name}</a>{index < item.authors.length - 1 ? "," : ""}</span>)}</div></div><ImportanceStars value={item.importance ?? null} onChange={(value) => void patch({ importance: value })} /></div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">{item.venue ? <span>{item.venue}</span> : null}{item.year ? <span>· {item.year}</span> : null}{item.doi ? <a href={`https://doi.org/${item.doi.replace("https://doi.org/", "")}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">DOI <ExternalLink className="h-3 w-3" /></a> : null}<a href={item.google_scholar_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">Google Scholar <ExternalLink className="h-3 w-3" /></a>{item.zotero_key ? <span>· Zotero {item.zotero_key}</span> : null}</div>
      <div className="mt-3 flex gap-2"><select value={item.status} onChange={(e) => void patch({ status: e.target.value as PaperStatus })} className="rounded-md border border-border bg-surface px-2 py-1 text-xs">{STATUSES.map((value) => <option key={value} value={value}>{statusLabel(locale, value)}</option>)}</select>{item.zotero_reader_url || item.pdf_path ? <button type="button" onClick={() => void openPaperDocument(item, locale, onMessage)} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-soft"><FileText className="h-3.5 w-3.5" />{L(locale, "打开 PDF", "Open PDF")}</button> : null}{item.url && !item.url.startsWith("file:") ? <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-soft">{L(locale, "原文", "Source")}<ExternalLink className="h-3.5 w-3.5" /></a> : null}</div>
    </div>
    {item.abstract ? <section><h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{L(locale, "摘要", "Abstract")}</h3><p className="whitespace-pre-wrap text-sm leading-relaxed text-muted">{item.abstract}</p></section> : null}
    <section><h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{L(locale, "标签", "Tags")}</h3><TagChipEditor tags={tags} suggestions={tagSuggestions} locale={locale} onChange={(next) => { setTags(next); void patch({ tags: next }); }} /></section>
    <section><h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{L(locale, "阅读笔记", "Reading notes")}</h3><RichNoteEditor value={item.user_note_html ?? ""} placeholder={L(locale, "记录方法、结论、引用与想法…", "Methods, findings, quotes, and ideas…")} onSave={(html) => updatePaper(item.id, { user_note_html: html }).then((saved) => { onSaved(saved); })} /></section>
    <section className="border-t border-border pt-4">{related.length ? <RelatedItemsSection items={related} locale={locale} titleLabel={L(locale, "相关内容", "Related") } lessRelevantLabel={L(locale, "不太相关", "Less relevant")} onSelect={handleRelatedSelect} onLessRelevant={(rawId) => { if (item.raw_id != null) void postRelatedLessRelevant(item.raw_id, rawId).then(() => setRelated((rows) => rows.filter((row) => row.raw_id !== rawId))); }} /> : <p className="text-sm text-muted">{L(locale, "添加标签后可发现库内相关论文、文章与视频。", "Add tags to discover related papers, articles, and videos.")}</p>}</section>
  </div></div>;
}

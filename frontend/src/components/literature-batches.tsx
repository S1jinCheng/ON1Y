"use client";

import { FileJson, Languages, Loader2, Plus, Rocket, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  bulkUpdatePaperStatus,
  createLiteratureBatch,
  enqueueLiteratureTranslations,
  fetchLiteratureBatch,
  fetchLiteratureDailyPlan,
  listLiteratureBatches,
  publishLiteratureBatch,
  rebuildLiteratureFeedback
} from "@/lib/api";
import type {
  LiteratureBatch,
  LiteratureDailyPlan,
  LiteraturePaperInput,
  LiteratureTranslationSummary,
  PaperStatus
} from "@/lib/paper-types";
import type { Locale } from "@/lib/types";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

function parseImport(text: string): LiteraturePaperInput[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[")) {
    const value = JSON.parse(trimmed) as unknown;
    if (!Array.isArray(value)) throw new Error("JSON root must be an array");
    return value as LiteraturePaperInput[];
  }
  return trimmed.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as LiteraturePaperInput);
}

function translationLabel(locale: Locale, value?: LiteratureTranslationSummary): string | null {
  if (!value || !value.eligible) return null;
  if (value.running || value.queued) {
    return L(locale, `翻译中 ${value.succeeded}/${value.eligible}`, `Translating ${value.succeeded}/${value.eligible}`);
  }
  if (value.failed) {
    return L(locale, `完成 ${value.succeeded}/${value.eligible} · 失败 ${value.failed}`,
      `${value.succeeded}/${value.eligible} ready · ${value.failed} failed`);
  }
  if (value.succeeded === value.eligible) {
    return L(locale, `双语 PDF ${value.succeeded}/${value.eligible}`, `Bilingual PDFs ${value.succeeded}/${value.eligible}`);
  }
  return L(locale, `待翻译 ${value.not_queued}`, `${value.not_queued} pending`);
}

export function LiteratureBatches(props: {
  locale: Locale;
  onMessage: (message: string) => void;
  onPublished: () => void;
}): JSX.Element {
  const { locale, onMessage, onPublished } = props;
  const [open, setOpen] = useState(false);
  const [field, setField] = useState("Human-AI Interaction");
  const [fieldCode, setFieldCode] = useState("HAI");
  const [batchDate, setBatchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [records, setRecords] = useState<LiteraturePaperInput[]>([]);
  const [title, setTitle] = useState("");
  const [doi, setDoi] = useState("");
  const [recommendation, setRecommendation] = useState("");
  const [pdfUrl, setPdfUrl] = useState("");
  const [batches, setBatches] = useState<LiteratureBatch[]>([]);
  const [activeBatch, setActiveBatch] = useState<LiteratureBatch | null>(null);
  const [dailyPlan, setDailyPlan] = useState<LiteratureDailyPlan | null>(null);
  const [selectedPapers, setSelectedPapers] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const projectionSignature = useRef<string | null>(null);
  const lastSelectedIndex = useRef<number | null>(null);
  const onPublishedRef = useRef(onPublished);
  const hasActiveTranslation = batches.some(
    (batch) => Boolean(batch.translation?.queued || batch.translation?.running)
  );
  useEffect(() => { onPublishedRef.current = onPublished; }, [onPublished]);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const next = (await listLiteratureBatches()).items;
      setBatches(next);
      const readingBatch = next.find((batch) => batch.status === "published");
      if (readingBatch) {
        setActiveBatch(await fetchLiteratureBatch(readingBatch.id));
      } else {
        setActiveBatch(null);
      }
      const signature = next
        .map((batch) => `${batch.id}:${batch.translation?.succeeded ?? 0}`)
        .join("|");
      if (projectionSignature.current !== null && projectionSignature.current !== signature) {
        onPublishedRef.current();
      }
      projectionSignature.current = signature;
    } catch {
      setBatches([]);
    }
  }, []);

  const refreshPlan = useCallback(async (): Promise<void> => {
    if (!field.trim() || !batchDate) return;
    try {
      setDailyPlan(await fetchLiteratureDailyPlan(batchDate, field.trim()));
    } catch {
      setDailyPlan(null);
    }
  }, [batchDate, field]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { void refreshPlan(); }, [refreshPlan]);
  useEffect(() => {
    if (!open && !hasActiveTranslation) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [hasActiveTranslation, open, refresh]);

  function addManual(): void {
    if (!title.trim() && !doi.trim()) return;
    setRecords((rows) => [...rows, {
      title: title.trim() || undefined,
      doi: doi.trim() || undefined,
      pdf_url: pdfUrl.trim() || undefined,
      recommendation: recommendation.trim()
    }]);
    setTitle("");
    setDoi("");
    setPdfUrl("");
    setRecommendation("");
  }

  async function importFile(file: File): Promise<void> {
    try {
      const imported = parseImport(await file.text());
      setRecords((rows) => [...rows, ...imported]);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function create(): Promise<void> {
    if (!field.trim() || !fieldCode.trim() || (!records.length && !dailyPlan?.carryover_count)) return;
    setBusy("create");
    try {
      const result = await createLiteratureBatch({
        field: field.trim(), field_code: fieldCode.trim(),
        batch_date: batchDate, papers: records
      });
      if (!result.created) {
        onMessage(L(locale, `校验失败：${result.errors.length} 个错误`, `Validation failed: ${result.errors.length} errors`));
        return;
      }
      onMessage(L(locale,
        `草稿已创建：结转 ${result.carryover_count ?? 0} 篇，新增 ${result.new_count ?? result.accepted.length} 篇，剩余 ${result.remaining_slots ?? 0} 个名额`,
        `Draft created: ${result.carryover_count ?? 0} carried, ${result.new_count ?? result.accepted.length} new, ${result.remaining_slots ?? 0} slots left`));
      setRecords([]);
      await refresh();
      await refreshPlan();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  function togglePaper(index: number, checked: boolean, shiftKey: boolean): void {
    const papers = activeBatch?.papers ?? [];
    setSelectedPapers((current) => {
      const next = new Set(current);
      if (shiftKey && lastSelectedIndex.current !== null) {
        const start = Math.min(index, lastSelectedIndex.current);
        const end = Math.max(index, lastSelectedIndex.current);
        for (let offset = start; offset <= end; offset += 1) {
          const paper = papers[offset];
          if (paper) checked ? next.add(paper.id) : next.delete(paper.id);
        }
      } else {
        const paper = papers[index];
        if (paper) checked ? next.add(paper.id) : next.delete(paper.id);
      }
      return next;
    });
    lastSelectedIndex.current = index;
  }

  async function applyReadingStatus(status: PaperStatus): Promise<void> {
    if (!selectedPapers.size) return;
    setBusy("reading-status");
    try {
      const result = await bulkUpdatePaperStatus({
        literature_paper_ids: [...selectedPapers], status
      });
      onMessage(L(locale, `已更新 ${result.updated} 篇论文`, `${result.updated} papers updated`));
      setSelectedPapers(new Set());
      await refresh();
      await refreshPlan();
      onPublished();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function publish(batch: LiteratureBatch): Promise<void> {
    setBusy(batch.id);
    try {
      await publishLiteratureBatch(batch.id);
      onMessage(L(locale, "批次已发布；符合设置时双语 PDF 已进入后台队列",
        "Batch published; bilingual PDFs were queued when enabled"));
      await refresh();
      onPublished();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function translate(batch: LiteratureBatch): Promise<void> {
    setBusy("translate-" + batch.id);
    try {
      const result = await enqueueLiteratureTranslations(batch.id);
      onMessage(L(locale, `已加入 ${result.queued_now} 篇，跳过 ${result.skipped} 篇`,
        `${result.queued_now} queued, ${result.skipped} skipped`));
      await refresh();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function feedback(batch: LiteratureBatch): Promise<void> {
    setBusy("feedback-" + batch.id);
    try {
      const result = await rebuildLiteratureFeedback(batch.id);
      onMessage(L(locale, `Feedback 已更新：已读 ${result.read}/${result.total}`,
        `Feedback updated: ${result.read}/${result.total} read`));
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  const latestBatch = batches[0];
  const latestTranslation = translationLabel(locale, latestBatch?.translation);

  return <div className="mb-3 rounded-lg border border-border bg-soft/30 p-2">
    <button type="button" onClick={() => setOpen((value) => !value)}
      className="flex w-full items-center justify-between text-xs font-medium">
      <span className="min-w-0 text-left">
        <span>Literature Vault</span>
        {latestBatch ? <span className="ml-2 font-normal text-muted">
          {latestBatch.batch_date} · {latestBatch.paper_count ?? 0}
          {latestTranslation ? ` · ${latestTranslation}` : ""}
        </span> : null}
      </span><span>{open ? "−" : "+"}</span>
    </button>
    {open ? <div className="mt-3 space-y-3">
      {activeBatch?.papers?.length ? <div className="space-y-2 rounded border border-border bg-surface p-2">
        <div className="flex items-center gap-2 text-xs font-medium">
          <span className="min-w-0 flex-1 truncate">
            {L(locale, "今日阅读", "Daily reading")} · {activeBatch.batch_date} · {activeBatch.field}
          </span>
          <span className="text-muted">
            {activeBatch.progress?.read ?? 0}/{activeBatch.progress?.total ?? activeBatch.papers.length}
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded bg-soft">
          <div className="h-full bg-emerald-500 transition-all" style={{ width: `${Math.round(
            ((activeBatch.progress?.read ?? 0) / Math.max(1, activeBatch.progress?.total ?? activeBatch.papers.length)) * 100
          )}%` }} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <label className="inline-flex cursor-pointer items-center gap-1">
            <input type="checkbox" checked={activeBatch.papers.every((paper) => selectedPapers.has(paper.id))}
              onChange={(event) => setSelectedPapers(event.target.checked
                ? new Set(activeBatch.papers?.map((paper) => paper.id) ?? []) : new Set())} />
            {L(locale, "全选", "Select all")}
          </label>
          {selectedPapers.size ? <>
            <span className="text-muted">{L(locale, `已选 ${selectedPapers.size} 篇`, `${selectedPapers.size} selected`)}</span>
            <button type="button" disabled={busy !== null} onClick={() => void applyReadingStatus("read")}
              className="rounded border border-border px-1.5 py-0.5">{L(locale, "标为已读", "Mark read")}</button>
            <button type="button" disabled={busy !== null} onClick={() => void applyReadingStatus("to_read")}
              className="rounded border border-border px-1.5 py-0.5">{L(locale, "撤销", "Undo")}</button>
            <button type="button" disabled={busy !== null} onClick={() => void applyReadingStatus("dismissed")}
              className="rounded border border-border px-1.5 py-0.5">{L(locale, "移出队列", "Dismiss")}</button>
          </> : null}
        </div>
        <div className="max-h-52 space-y-1 overflow-y-auto pr-1">
          {activeBatch.papers.map((paper, index) => <label key={paper.id}
            className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 text-[11px] hover:bg-soft">
            <input type="checkbox" className="mt-0.5" checked={selectedPapers.has(paper.id)}
              onChange={(event) => togglePaper(index, event.target.checked, (event.nativeEvent as MouseEvent).shiftKey)} />
            <span className="w-6 shrink-0 text-right text-muted">{String(paper.position).padStart(2, "0")}</span>
            <span className="min-w-0 flex-1 line-clamp-2">{paper.title}</span>
            <span className={paper.status === "read" ? "text-emerald-600" : paper.status === "dismissed" ? "text-muted" : "text-amber-600"}>
              {paper.status === "read" ? L(locale, "已读", "Read") : paper.status === "dismissed" ? L(locale, "移出", "Dismissed") : L(locale, "待读", "Unread")}
            </span>
          </label>)}
        </div>
      </div> : null}
      {dailyPlan ? <div className="rounded border border-border bg-surface px-2 py-1.5 text-[11px] text-muted">
        {L(locale,
          `${dailyPlan.target_date}：结转 ${dailyPlan.carryover_count} 篇，可新增 ${dailyPlan.new_slots} 篇，每日目标 ${dailyPlan.daily_target}`,
          `${dailyPlan.target_date}: ${dailyPlan.carryover_count} carried, ${dailyPlan.new_slots} new slots, target ${dailyPlan.daily_target}`)}
        {dailyPlan.blocking_fields.length ? <div className="mt-1 text-amber-600">
          {L(locale, `需先清完领域：${dailyPlan.blocking_fields.join("、")}`, `Finish first: ${dailyPlan.blocking_fields.join(", ")}`)}
        </div> : null}
      </div> : null}
      <div className="grid grid-cols-3 gap-2">
        <input value={field} onChange={(e) => setField(e.target.value)}
          className="rounded border border-border bg-surface px-2 py-1 text-xs" placeholder={L(locale, "领域", "Field")} />
        <input value={fieldCode} onChange={(e) => setFieldCode(e.target.value)}
          className="rounded border border-border bg-surface px-2 py-1 text-xs" placeholder="Code" />
        <input type="date" value={batchDate} onChange={(e) => setBatchDate(e.target.value)}
          className="rounded border border-border bg-surface px-2 py-1 text-xs" />
      </div>
      <div className="space-y-2 rounded border border-border bg-surface p-2">
        <input value={title} onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded border border-border px-2 py-1 text-xs" placeholder={L(locale, "论文标题", "Paper title")} />
        <div className="grid grid-cols-2 gap-2">
          <input value={doi} onChange={(e) => setDoi(e.target.value)}
            className="rounded border border-border px-2 py-1 text-xs" placeholder="DOI" />
          <input value={pdfUrl} onChange={(e) => setPdfUrl(e.target.value)}
            className="rounded border border-border px-2 py-1 text-xs" placeholder="PDF URL" />
        </div>
        <input value={recommendation} onChange={(e) => setRecommendation(e.target.value)}
          className="w-full rounded border border-border px-2 py-1 text-xs" placeholder={L(locale, "一句推荐理由", "One-line recommendation")} />
        <button type="button" onClick={addManual} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs">
          <Plus className="h-3 w-3" />{L(locale, "加入清单", "Add")}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-2 py-1">
          <FileJson className="h-3 w-3" />JSON / JSONL
          <input type="file" accept=".json,.jsonl,application/json" className="hidden"
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void importFile(file); }} />
        </label>
        <span className="text-muted">{records.length} {L(locale, "篇待校验", "pending")}</span>
        <button type="button" disabled={
          (!records.length && !dailyPlan?.carryover_count)
          || Boolean(dailyPlan?.blocking_fields.length)
          || busy !== null
        } onClick={() => void create()}
          className="ml-auto rounded bg-inverse px-2 py-1 text-inverse-foreground disabled:opacity-50">
          {busy === "create" ? <Loader2 className="h-3 w-3 animate-spin" /> : L(locale, "创建草稿", "Create draft")}
        </button>
      </div>
      {batches.length ? <div className="space-y-2 border-t border-border pt-2">
        {batches.slice(0, 5).map((batch) => {
          const translation = batch.translation;
          const label = translationLabel(locale, translation);
          const translating = Boolean(translation?.running || translation?.queued);
          const canTranslate = batch.status === "published" && Boolean(translation?.eligible)
            && translation?.state !== "ready";
          return <div key={batch.id} className="rounded border border-border/70 bg-surface/70 px-2 py-1.5">
            <div className="flex items-center gap-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate">{batch.batch_date} · {batch.field} · {batch.paper_count ?? 0}</span>
              <span className="text-muted">{batch.status}</span>
              {batch.status === "draft" || batch.status === "error" ? <button type="button" onClick={() => void publish(batch)}
                disabled={busy !== null} title={L(locale, "发布", "Publish")}><Rocket className="h-3.5 w-3.5" /></button> : null}
              {canTranslate ? <button type="button" onClick={() => void translate(batch)} disabled={busy !== null || translating}
                title={translation?.failed ? L(locale, "重试失败项", "Retry failed") : L(locale, "生成双语 PDF", "Create bilingual PDFs")}>
                {busy === "translate-" + batch.id || translating
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Languages className="h-3.5 w-3.5" />}
              </button> : null}
              {batch.status === "published" ? <button type="button" onClick={() => void feedback(batch)}
                disabled={busy !== null} title="Feedback"><RotateCcw className="h-3.5 w-3.5" /></button> : null}
            </div>
            {label ? <div className="mt-1 flex items-center gap-2 text-[10px] text-muted">
              <span>{label}</span>
              {translation?.total_tokens ? <span>{translation.total_tokens.toLocaleString()} tokens</span> : null}
              {translation?.character_count ? <span>{translation.character_count.toLocaleString()} chars</span> : null}
            </div> : null}
            {translating && translation ? <div className="mt-1 h-1 overflow-hidden rounded bg-soft">
              <div className="h-full bg-foreground/60 transition-all"
                style={{ width: `${Math.max(3, (translation.succeeded / Math.max(1, translation.eligible)) * 100)}%` }} />
            </div> : null}
          </div>;
        })}
      </div> : null}
    </div> : null}
  </div>;
}

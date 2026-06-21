"use client";

import { BookOpen, CheckCircle2, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { buildAcquireNotice, KindleStatusBlock, type BookAcquireNotice } from "@/components/book-acquire-notice";
import { acquireBook, previewAcquireBook } from "@/lib/api";
import { bookCoverSrc } from "@/lib/book-cover";
import type { BookAcquireCandidate, BookAcquirePreview, BookAcquireResult } from "@/lib/book-types";
import { candidateDoubanMismatch } from "@/lib/translator-match";
import type { Locale } from "@/lib/types";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

const SOURCE_LABEL: Record<string, { zh: string; en: string }> = {
  zlib: { zh: "Z-Library", en: "Z-Library" },
  annas: { zh: "安娜档案", en: "Anna's Archive" }
};

export type BookAcquireRequest = {
  title: string;
  author?: string | null;
  translator?: string | null;
  publisher?: string | null;
  isbn?: string | null;
  douban_url?: string | null;
  cover_url?: string | null;
  add_to_shelf: boolean;
  shelf_item_id?: number;
};

type UseBookAcquireConfirmOptions = {
  locale: Locale;
  onAcquireNotice: (notice: BookAcquireNotice | null) => void;
  onMessage?: (message: string) => void;
  onSuccess?: (result: BookAcquireResult, request: BookAcquireRequest) => void | Promise<void>;
};

export function useBookAcquireConfirm(options: UseBookAcquireConfirmOptions) {
  const { locale, onAcquireNotice, onMessage, onSuccess } = options;
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [preview, setPreview] = useState<BookAcquirePreview | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [pending, setPending] = useState<BookAcquireRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successResult, setSuccessResult] = useState<BookAcquireResult | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const close = useCallback(() => {
    if (confirming) return;
    setOpen(false);
    setPreview(null);
    setPending(null);
    setSelectedIndex(0);
    setError(null);
    setSuccessResult(null);
    setLoading(false);
  }, [confirming]);

  const finishSuccess = useCallback(() => {
    if (successResult) {
      onAcquireNotice(buildAcquireNotice(locale, successResult));
    }
    close();
  }, [close, locale, onAcquireNotice, successResult]);

  const startAcquire = useCallback(
    async (request: BookAcquireRequest) => {
      setOpen(true);
      setLoading(true);
      setPreview(null);
      setSelectedIndex(0);
      setPending(request);
      setError(null);
      setSuccessResult(null);
      try {
        const result = await previewAcquireBook({
          title: request.title,
          author: request.author,
          translator: request.translator,
          publisher: request.publisher,
          isbn: request.isbn,
          douban_url: request.douban_url,
          cover_url: request.cover_url
        });
        setPreview(result);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        onAcquireNotice({ message, kind: "error" });
        onMessage?.(message);
        setOpen(false);
        setPending(null);
      } finally {
        setLoading(false);
      }
    },
    [onAcquireNotice, onMessage]
  );

  const confirmAcquire = useCallback(async () => {
    if (!preview || !pending || confirming || successResult) return;
    const candidate = preview.candidates[selectedIndex];
    if (!candidate) return;
    setConfirming(true);
    setError(null);
    try {
      const result = await acquireBook({
        title: pending.title,
        author: pending.author,
        translator: pending.translator,
        publisher: pending.publisher,
        isbn: pending.isbn,
        douban_url: pending.douban_url,
        add_to_shelf: pending.add_to_shelf,
        shelf_item_id: pending.shelf_item_id,
        candidate
      });
      try {
        await onSuccess?.(result, pending);
      } catch (sideErr) {
        const sideMsg = sideErr instanceof Error ? sideErr.message : String(sideErr);
        onMessage?.(sideMsg);
      }
      setSuccessResult(result);
      onAcquireNotice(buildAcquireNotice(locale, result));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      onAcquireNotice({ message, kind: "error" });
      onMessage?.(message);
    } finally {
      setConfirming(false);
    }
  }, [
    preview,
    pending,
    confirming,
    successResult,
    selectedIndex,
    locale,
    onAcquireNotice,
    onMessage,
    onSuccess
  ]);

  const dialog =
    mounted && open ? (
      <BookAcquireConfirmDialog
        locale={locale}
        preview={preview}
        selectedIndex={selectedIndex}
        onSelect={setSelectedIndex}
        loading={loading}
        confirming={confirming}
        error={error}
        successResult={successResult}
        onConfirm={() => void confirmAcquire()}
        onCancel={close}
        onDone={finishSuccess}
      />
    ) : null;

  return { startAcquire, acquireDialog: dialog };
}

type DialogProps = {
  locale: Locale;
  preview: BookAcquirePreview | null;
  selectedIndex: number;
  onSelect: (index: number) => void;
  loading: boolean;
  confirming: boolean;
  error: string | null;
  successResult: BookAcquireResult | null;
  onConfirm: () => void;
  onCancel: () => void;
  onDone: () => void;
};

function BookAcquireConfirmDialog(props: DialogProps): JSX.Element {
  const {
    locale,
    preview,
    selectedIndex,
    onSelect,
    loading,
    confirming,
    error,
    successResult,
    onConfirm,
    onCancel,
    onDone
  } = props;

  const successNotice = successResult ? buildAcquireNotice(locale, successResult) : null;

  const sourceLabel = preview
    ? L(locale, SOURCE_LABEL[preview.source]?.zh ?? preview.source, SOURCE_LABEL[preview.source]?.en ?? preview.source)
    : "";

  const formatNote = (() => {
    const filters = preview?.format_filters ?? [];
    if (filters.length === 0) {
      return L(locale, "不限格式 · 各取前 3", "Any format · top 3");
    }
    if (filters.length === 1) {
      return L(locale, `仅 ${filters[0].toUpperCase()} · 前 3`, `${filters[0].toUpperCase()} only · top 3`);
    }
    const label = filters.map((f) => f.toUpperCase()).join(" / ");
    return L(
      locale,
      `${label} · 各格式前 3（共 ${preview?.candidates.length ?? filters.length * 3} 条）`,
      `${label} · top 3 per format (${preview?.candidates.length ?? filters.length * 3} total)`
    );
  })();

  const dialog = (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !confirming) {
          if (successResult) {
            onDone();
          } else {
            onCancel();
          }
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              {successResult
                ? L(locale, "下载完成", "Download complete")
                : L(locale, "选择电子书版本", "Choose an edition")}
            </h3>
            <p className="mt-1 text-xs text-muted">
              {successResult
                ? L(locale, "文件已保存到本地缓存", "File saved to local cache")
                : L(
                    locale,
                    "按设置中的格式筛选：每种勾选格式各取最受欢迎前 3 条",
                    "Per checked format in settings: top 3 Z-Library results by popularity for each"
                  )}
            </p>
          </div>
          <button
            type="button"
            className="rounded p-1 text-muted hover:bg-muted/20"
            onClick={successResult ? onDone : onCancel}
            disabled={confirming}
            aria-label={L(locale, "关闭", "Close")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
              <Loader2 className="h-5 w-5 animate-spin" />
              {L(locale, "正在搜索…", "Searching…")}
            </div>
          ) : confirming ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-muted">
              <Loader2 className="h-8 w-8 animate-spin" />
              <p>{L(locale, "正在下载，大文件可能需要几分钟…", "Downloading — large files may take a few minutes…")}</p>
            </div>
          ) : successResult && successNotice ? (
            <div className="flex flex-col items-center gap-4 py-10 text-center">
              <CheckCircle2 className="h-12 w-12 text-emerald-600 dark:text-emerald-400" />
              <p className="max-w-md text-sm font-medium leading-relaxed text-foreground">{successNotice.message}</p>
              <KindleStatusBlock
                locale={locale}
                result={successResult}
                hasLocalFile={Boolean(successResult.local_path)}
                notes={successResult.shelf_item?.notes}
              />
              {successResult.local_path ? (
                <p className="max-w-md break-all text-xs text-muted">{successResult.local_path}</p>
              ) : null}
            </div>
          ) : error ? (
            <p className="py-8 text-center text-sm text-destructive">{error}</p>
          ) : preview ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-border/70 bg-muted/10 px-3 py-2.5">
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted">
                  {L(locale, "豆瓣条目", "Douban edition")}
                </p>
                <p className="mt-1 text-sm font-medium text-foreground">{preview.douban.title}</p>
                <p className="text-xs text-muted">
                  {[preview.douban.author, preview.douban.translator, preview.douban.publisher]
                    .filter(Boolean)
                    .join(" / ")}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span>
                  {L(locale, "搜索词", "Query")}: <span className="text-foreground">{preview.search_query}</span>
                </span>
                <span>·</span>
                <span>
                  {L(locale, "格式", "Format")}: {formatNote}
                </span>
                <span>·</span>
                <span>{sourceLabel}</span>
              </div>

              <div className="space-y-2">
                {preview.candidates.map((candidate, index) => (
                  <CandidateRow
                    key={`${candidate.book_id ?? candidate.md5 ?? index}-${candidate.title}`}
                    locale={locale}
                    candidate={candidate}
                    doubanTranslator={preview.douban.translator}
                    index={index}
                    selected={selectedIndex === index}
                    onSelect={() => onSelect(index)}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
          {successResult ? (
            <button
              type="button"
              className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background"
              onClick={onDone}
            >
              {L(locale, "完成", "Done")}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="rounded-md px-3 py-1.5 text-sm text-muted hover:bg-muted/20"
                onClick={onCancel}
                disabled={confirming}
              >
                {L(locale, "取消", "Cancel")}
              </button>
              <button
                type="button"
                className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
                onClick={onConfirm}
                disabled={loading || confirming || !preview?.candidates.length}
              >
                {L(locale, "确认下载并推送", "Download & send")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}

function CandidateRow(props: {
  locale: Locale;
  candidate: BookAcquireCandidate;
  doubanTranslator?: string | null;
  index: number;
  selected: boolean;
  onSelect: () => void;
}): JSX.Element {
  const { candidate, doubanTranslator, index, selected, onSelect, locale } = props;
  const mismatch = candidateDoubanMismatch(doubanTranslator, candidate);
  const meta = [
    candidate.format.toUpperCase(),
    candidate.publisher,
    candidate.year,
    candidate.language,
    candidate.filesize
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full gap-3 rounded-lg border p-3 text-left transition-colors ${
        selected
          ? "border-foreground/40 bg-foreground/5 ring-1 ring-foreground/20"
          : "border-border hover:border-foreground/20 hover:bg-muted/10"
      }`}
    >
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-medium text-muted">
        {index + 1}
      </div>
      <CoverImage url={candidate.cover_url} title={candidate.title} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-snug text-foreground">{candidate.title}</p>
        {candidate.author ? <p className="mt-0.5 text-xs text-muted line-clamp-2">{candidate.author}</p> : null}
        {mismatch ? (
          <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">
            {L(
              locale,
              "与豆瓣检索译者不一致，入库将按此版本记录",
              "Differs from Douban translator — shelf will use this edition"
            )}
          </p>
        ) : null}
        {meta ? <p className="mt-1 text-[11px] text-muted">{meta}</p> : null}
      </div>
      <div
        className={`mt-1 h-4 w-4 shrink-0 rounded-full border-2 ${
          selected ? "border-foreground bg-foreground" : "border-muted"
        }`}
        aria-hidden
      />
    </button>
  );
}

function CoverImage(props: { url?: string | null; title: string }): JSX.Element {
  const { url, title } = props;
  const [failed, setFailed] = useState(false);

  if (!url || failed) {
    return (
      <div className="flex h-[72px] w-[52px] shrink-0 items-center justify-center rounded border border-border bg-muted/20">
        <BookOpen className="h-5 w-5 text-muted" />
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={bookCoverSrc(url)}
      alt={title}
      className="h-[72px] w-[52px] shrink-0 rounded border border-border object-cover"
      onError={() => setFailed(true)}
    />
  );
}

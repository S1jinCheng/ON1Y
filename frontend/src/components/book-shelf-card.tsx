"use client";

import {
  BookOpen,
  CheckCircle2,
  Circle,
  Download,
  FolderOpen,
  Loader2,
  Send,
  Star,
  Trash2
} from "lucide-react";
import { useState } from "react";

import { bookCoverSrc } from "@/lib/book-cover";
import type { BookShelfItem, BookStatus } from "@/lib/book-types";
import type { Locale } from "@/lib/types";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

function statusLabel(locale: Locale, status: BookStatus): string {
  if (locale === "zh") {
    return status === "reading" ? "在读" : "已读";
  }
  return status === "reading" ? "Reading" : "Read";
}

function ActionBtn(props: {
  label: string;
  onClick: (e: React.MouseEvent) => void;
  disabled?: boolean;
  className?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      aria-label={props.label}
      title={props.label}
      disabled={props.disabled}
      onClick={props.onClick}
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-soft hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 ${props.className ?? ""}`}
    >
      {props.children}
    </button>
  );
}

export type BookShelfCardProps = {
  item: BookShelfItem;
  locale: Locale;
  active: boolean;
  selected: boolean;
  selectionMode: boolean;
  hasLocalFile: boolean;
  cachedReady: boolean;
  primaryPath: string | null;
  kindleBusy?: boolean;
  restoreBusy?: boolean;
  canRestore: boolean;
  onSelect: () => void;
  onToggleSelected: () => void;
  onToggleFavorite: () => void;
  onOpenLocal: () => void;
  onSendKindle: () => void;
  onRestoreDownload: () => void;
  onDelete: () => void;
};

export function BookShelfCard(props: BookShelfCardProps): JSX.Element {
  const {
    item,
    locale,
    active,
    selected,
    selectionMode,
    hasLocalFile,
    cachedReady,
    kindleBusy,
    restoreBusy,
    canRestore,
    onSelect,
    onToggleSelected,
    onToggleFavorite,
    onOpenLocal,
    onSendKindle,
    onRestoreDownload,
    onDelete
  } = props;

  const [confirmDelete, setConfirmDelete] = useState(false);
  const starred = (item.importance ?? 0) >= 1;

  function handleContentClick(): void {
    if (selectionMode) {
      onToggleSelected();
      return;
    }
    onSelect();
  }

  return (
    <div
      className={`flex overflow-hidden rounded-lg border transition-colors ${
        selectionMode && selected
          ? "border-foreground bg-soft ring-1 ring-foreground"
          : active
            ? "border-foreground bg-soft"
            : "border-border bg-surface hover:bg-panel"
      }`}
    >
      <button type="button" onClick={handleContentClick} className="min-w-0 flex-1 p-2.5 text-left">
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
                {statusLabel(locale, item.status === "read" ? "read" : "reading")}
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

      <div
        className="flex shrink-0 flex-col items-center justify-center gap-0 border-l border-border bg-panel/80 py-1"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={() => undefined}
        role="presentation"
      >
        <ActionBtn
          label={L(locale, "全选", "Select all")}
          className={selected ? "text-foreground" : ""}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelected();
          }}
        >
          {selected ? (
            <CheckCircle2 className="h-4 w-4 fill-foreground text-background" />
          ) : (
            <Circle className="h-4 w-4" />
          )}
        </ActionBtn>

        {!selectionMode ? (
          <>
            <ActionBtn
              label={L(locale, starred ? "取消收藏" : "收藏", starred ? "Unfavorite" : "Favorite")}
              onClick={(e) => {
                e.stopPropagation();
                onToggleFavorite();
              }}
            >
              <Star className={`h-4 w-4 ${starred ? "fill-amber-400 text-amber-500" : ""}`} />
            </ActionBtn>

            {cachedReady && !hasLocalFile && canRestore ? (
              <ActionBtn
                label={L(locale, "重新下载", "Re-download")}
                disabled={restoreBusy}
                onClick={(e) => {
                  e.stopPropagation();
                  onRestoreDownload();
                }}
              >
                {restoreBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
              </ActionBtn>
            ) : null}

            {cachedReady && hasLocalFile ? (
              <>
                <ActionBtn
                  label={L(locale, "打开本地文件", "Open local file")}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenLocal();
                  }}
                >
                  <FolderOpen className="h-4 w-4" />
                </ActionBtn>
                <ActionBtn
                  label={L(locale, "推送到 Kindle", "Send to Kindle")}
                  disabled={kindleBusy}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSendKindle();
                  }}
                >
                  {kindleBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </ActionBtn>
              </>
            ) : null}

            {confirmDelete ? (
              <ActionBtn
                label={L(locale, "确认删除", "Confirm delete")}
                className="text-red-600 hover:bg-red-500/10 hover:text-red-500"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                  setConfirmDelete(false);
                }}
              >
                <Trash2 className="h-4 w-4" />
              </ActionBtn>
            ) : (
              <ActionBtn
                label={L(locale, "删除", "Delete")}
                className="hover:text-red-500"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmDelete(true);
                }}
              >
                <Trash2 className="h-4 w-4" />
              </ActionBtn>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

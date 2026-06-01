"use client";

import { FileDown, FileText, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { RichNoteEditor } from "@/components/rich-note-editor";
import { exportItemDocument } from "@/lib/export-document";
import { formatOriginalText, originalTextToHtml } from "@/lib/format-original-text";
import type { Locale } from "@/lib/types";

type NotesPanelProps = {
  rawId: number;
  title: string;
  summary: string;
  bodyText: string;
  translatedBodyText?: string | null;
  noteHtml: string;
  locale: Locale;
  labels: {
    notes: string;
    notesPlaceholder: string;
    saveNote: string;
    upload: string;
    chooseFile: string;
    uploadClassify: string;
    exportWord: string;
    exportPdf: string;
    summary: string;
    originalText: string;
  };
  onSaveNote: (html: string) => Promise<void>;
  onUpload: (file: File) => Promise<void>;
};

export function NotesPanel(props: NotesPanelProps): JSX.Element {
  const {
    rawId,
    title,
    summary,
    bodyText,
    translatedBodyText,
    noteHtml,
    locale,
    labels,
    onSaveNote,
    onUpload
  } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  async function handleUpload(file: File): Promise<void> {
    setUploading(true);
    try {
      await onUpload(file);
    } finally {
      setUploading(false);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    }
  }

  function buildExportSections(noteOverride?: string): {
    summaryHtml: string;
    originalHtml: string;
    notesHtml: string;
  } {
    const cleaned = formatOriginalText(bodyText, { locale, translatedBodyText });
    return {
      summaryHtml: `<div>${escapeHtml(summary).replace(/\n/g, "<br/>")}</div>`,
      originalHtml: originalTextToHtml(cleaned),
      notesHtml: noteOverride ?? noteHtml
    };
  }

  function handleExport(format: "word" | "pdf"): void {
    const sections = buildExportSections();
    exportItemDocument({
      title: title || "On1y Export",
      ...sections,
      format,
      labels: {
        summary: labels.summary,
        original: labels.originalText,
        notes: labels.notes
      }
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <h2 className="mr-auto text-xs font-medium uppercase tracking-wider text-muted">
          {labels.notes}
        </h2>
        <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft">
          <Upload className="h-3.5 w-3.5" />
          {uploading ? "…" : labels.upload}
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                void handleUpload(file);
              }
            }}
          />
        </label>
        <button
          type="button"
          onClick={() => handleExport("word")}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
        >
          <FileText className="h-3.5 w-3.5" />
          {labels.exportWord}
        </button>
        <button
          type="button"
          onClick={() => handleExport("pdf")}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-soft"
        >
          <FileDown className="h-3.5 w-3.5" />
          {labels.exportPdf}
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <RichNoteEditor
          key={rawId}
          value={noteHtml}
          placeholder={labels.notesPlaceholder}
          saveLabel={labels.saveNote}
          onSave={onSaveNote}
        />
      </div>
    </div>
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

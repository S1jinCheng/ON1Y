"use client";

import { Bold, Italic, Save, Type, Underline } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type RichNoteEditorProps = {
  value: string;
  placeholder: string;
  saveLabel: string;
  disabled?: boolean;
  onSave: (html: string) => Promise<void>;
};

type FontSize = "small" | "normal" | "large";

export function RichNoteEditor(props: RichNoteEditorProps): JSX.Element {
  const { value, placeholder, saveLabel, disabled, onSave } = props;
  const editorRef = useRef<HTMLDivElement>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const el = editorRef.current;
    if (!el || dirty) {
      return;
    }
    if (el.innerHTML !== value) {
      el.innerHTML = value || "";
    }
  }, [value, dirty]);

  const exec = useCallback((command: string, commandValue?: string) => {
    editorRef.current?.focus();
    document.execCommand(command, false, commandValue);
    setDirty(true);
  }, []);

  function applyFontSize(size: FontSize): void {
    const map: Record<FontSize, string> = {
      small: "2",
      normal: "3",
      large: "5"
    };
    exec("fontSize", map[size]);
  }

  async function handleSave(): Promise<void> {
    const html = editorRef.current?.innerHTML ?? "";
    setSaving(true);
    try {
      await onSave(html);
      setDirty(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-white">
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border px-2 py-1.5">
        <ToolbarButton
          title="Bold"
          onClick={() => exec("bold")}
          disabled={disabled}
        >
          <Bold className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title="Italic"
          onClick={() => exec("italic")}
          disabled={disabled}
        >
          <Italic className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title="Underline"
          onClick={() => exec("underline")}
          disabled={disabled}
        >
          <Underline className="h-4 w-4" />
        </ToolbarButton>
        <span className="mx-1 h-4 w-px bg-border" />
        <ToolbarButton title="Small" onClick={() => applyFontSize("small")} disabled={disabled}>
          <Type className="h-3.5 w-3.5" />
          <span className="text-[10px]">S</span>
        </ToolbarButton>
        <ToolbarButton title="Normal" onClick={() => applyFontSize("normal")} disabled={disabled}>
          <Type className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton title="Large" onClick={() => applyFontSize("large")} disabled={disabled}>
          <Type className="h-5 w-5" />
        </ToolbarButton>
        <span className="mx-1 h-4 w-px bg-border" />
        <select
          disabled={disabled}
          onChange={(e) => exec("fontName", e.target.value)}
          className="rounded border border-border bg-white px-1.5 py-0.5 text-xs outline-none"
          defaultValue=""
        >
          <option value="" disabled>
            Font
          </option>
          <option value="Georgia, serif">Serif</option>
          <option value="ui-monospace, monospace">Mono</option>
          <option value="system-ui, sans-serif">Sans</option>
        </select>
        <div className="ml-auto">
          <button
            type="button"
            disabled={disabled || saving || !dirty}
            onClick={() => void handleSave()}
            className="inline-flex items-center gap-1 rounded border border-black bg-black px-2 py-1 text-xs text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Save className="h-3.5 w-3.5" />
            {saveLabel}
          </button>
        </div>
      </div>
      <div
        ref={editorRef}
        contentEditable={!disabled}
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={() => setDirty(true)}
        className="note-editor min-h-0 flex-1 overflow-y-auto px-3 py-3 text-sm leading-relaxed text-black outline-none [&:empty:before]:text-neutral-400 [&:empty:before]:content-[attr(data-placeholder)]"
      />
    </div>
  );
}

function ToolbarButton(props: {
  children: React.ReactNode;
  title: string;
  onClick: () => void;
  disabled?: boolean;
}): JSX.Element {
  return (
    <button
      type="button"
      title={props.title}
      disabled={props.disabled}
      onClick={props.onClick}
      className="inline-flex items-center gap-0.5 rounded p-1 text-neutral-700 hover:bg-soft disabled:opacity-40"
    >
      {props.children}
    </button>
  );
}

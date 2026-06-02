"use client";

import { Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

const TAG_PALETTE = [
  "bg-rose-100 text-rose-800 border-rose-200",
  "bg-sky-100 text-sky-800 border-sky-200",
  "bg-emerald-100 text-emerald-800 border-emerald-200",
  "bg-amber-100 text-amber-900 border-amber-200",
  "bg-violet-100 text-violet-800 border-violet-200",
  "bg-teal-100 text-teal-800 border-teal-200",
  "bg-orange-100 text-orange-800 border-orange-200",
  "bg-indigo-100 text-indigo-800 border-indigo-200"
];

const COMMON_TAGS_ZH = [
  "教程",
  "深度",
  "访谈",
  "综述",
  "观点",
  "案例",
  "工具",
  "方法论",
  "入门",
  "进阶"
];

const COMMON_TAGS_EN = [
  "tutorial",
  "deep-dive",
  "interview",
  "review",
  "opinion",
  "case-study",
  "tools",
  "methodology",
  "beginner",
  "advanced"
];

/** Gray chips on feed / hot-list column cards (matches theme feed rows). */
export const feedItemListTagClass =
  "rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-700";

export function itemTagChipClass(name: string): string {
  return `rounded border px-1.5 py-0.5 text-[10px] ${tagColorClass(name)}`;
}

function tagColorClass(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return TAG_PALETTE[Math.abs(hash) % TAG_PALETTE.length];
}

function normalizeTag(raw: string): string {
  return raw.trim().replace(/^#+/, "");
}

type TagChipEditorProps = {
  tags: string[];
  suggestions: string[];
  locale: "zh" | "en";
  onChange: (tags: string[]) => void;
  disabled?: boolean;
};

export function TagChipEditor(props: TagChipEditorProps): JSX.Element {
  const { tags, suggestions, locale, onChange, disabled } = props;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [recentTags, setRecentTags] = useState<string[]>([]);
  const popoverRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("on1y-recent-tags");
      if (raw) {
        const parsed = JSON.parse(raw) as string[];
        if (Array.isArray(parsed)) {
          setRecentTags(parsed.filter((x) => typeof x === "string"));
        }
      }
    } catch {
      /* ignore */
    }
  }, []);

  const commonTags = locale === "zh" ? COMMON_TAGS_ZH : COMMON_TAGS_EN;

  const pickList = useMemo(() => {
    const seen = new Set(tags.map((t) => t.toLowerCase()));
    const merged = [...recentTags, ...commonTags, ...suggestions];
    const out: string[] = [];
    for (const item of merged) {
      const name = normalizeTag(item);
      if (!name) {
        continue;
      }
      const key = name.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      if (out.some((x) => x.toLowerCase() === key)) {
        continue;
      }
      out.push(name);
    }
    return out.slice(0, 24);
  }, [commonTags, recentTags, suggestions, tags]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onDocClick(event: MouseEvent): void {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  function rememberTag(name: string): void {
    const normalized = normalizeTag(name);
    if (!normalized) {
      return;
    }
    setRecentTags((prev) => {
      const next = [normalized, ...prev.filter((x) => x.toLowerCase() !== normalized.toLowerCase())].slice(
        0,
        30
      );
      localStorage.setItem("on1y-recent-tags", JSON.stringify(next));
      return next;
    });
  }

  function addTag(raw: string): void {
    const name = normalizeTag(raw);
    if (!name) {
      return;
    }
    const exists = tags.some((t) => t.toLowerCase() === name.toLowerCase());
    if (exists) {
      return;
    }
    rememberTag(name);
    onChange([...tags, name]);
    setDraft("");
  }

  function removeTag(name: string): void {
    onChange(tags.filter((t) => t !== name));
  }

  function toggleOpen(): void {
    if (disabled) {
      return;
    }
    setOpen((v) => !v);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className="relative">
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${tagColorClass(tag)}`}
          >
            #{tag}
            {!disabled ? (
              <button
                type="button"
                onClick={() => removeTag(tag)}
                className="rounded p-0.5 hover:bg-black/10"
                aria-label={`Remove ${tag}`}
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        ))}
        {!disabled ? (
          <div className="relative" ref={popoverRef}>
            <button
              type="button"
              onClick={toggleOpen}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-dashed border-neutral-300 text-neutral-600 hover:border-black hover:text-black"
              aria-label="Add tag"
            >
              <Plus className="h-4 w-4" />
            </button>
            {open ? (
              <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-border bg-white p-2 shadow-lg">
                <input
                  ref={inputRef}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTag(draft);
                    }
                    if (e.key === "Escape") {
                      setOpen(false);
                    }
                  }}
                  placeholder={locale === "zh" ? "输入新标签…" : "New tag…"}
                  className="mb-2 w-full rounded border border-border px-2 py-1 text-xs outline-none focus:border-black"
                />
                <div className="max-h-40 overflow-y-auto">
                  <div className="flex flex-wrap gap-1">
                    {pickList.map((tag) => (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => addTag(tag)}
                        className={`rounded-md border px-2 py-0.5 text-[11px] ${tagColorClass(tag)} hover:opacity-90`}
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                  {pickList.length === 0 ? (
                    <p className="px-1 py-2 text-[11px] text-muted">
                      {locale === "zh" ? "输入后回车添加" : "Type and press Enter"}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

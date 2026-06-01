"use client";

import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { themeDisplayName } from "@/lib/i18n";
import type { Locale, ThemeRow } from "@/lib/types";

export function ThemeMovePopover(props: {
  themes: ThemeRow[];
  locale: Locale;
  currentThemeId?: number | null;
  onSelect: (themeId: number) => void;
  trigger: React.ReactNode;
  /** Fixed panel to the right of trigger (avoids overflow clipping in narrow columns). */
  floatPanel?: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !props.floatPanel || !triggerRef.current) {
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const panelWidth = 192;
    const gap = 8;
    let left = rect.right + gap;
    const top = Math.max(8, Math.min(rect.top, window.innerHeight - 280));
    if (left + panelWidth > window.innerWidth - 8) {
      left = rect.left - panelWidth - gap;
    }
    setPanelPos({ top, left });
  }, [open, props.floatPanel]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onDocClick(event: MouseEvent): void {
      const target = event.target as Node;
      if (wrapRef.current?.contains(target)) {
        return;
      }
      const portal = document.getElementById("theme-move-popover-portal");
      if (portal?.contains(target)) {
        return;
      }
      setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const list = (
    <div className="max-h-64 w-48 overflow-y-auto rounded-lg border border-border bg-white py-1 shadow-xl">
      {props.themes.map((theme) => (
        <button
          key={theme.id}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            props.onSelect(theme.id);
            setOpen(false);
          }}
          className={`block w-full px-3 py-2 text-left text-sm hover:bg-soft ${
            props.currentThemeId === theme.id ? "font-medium text-black" : "text-neutral-700"
          }`}
        >
          {themeDisplayName(theme, props.locale)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="relative" ref={wrapRef}>
      <div
        ref={triggerRef}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={() => undefined}
        role="presentation"
      >
        {props.trigger}
      </div>
      {open && !props.floatPanel ? (
        <div className="absolute right-0 top-full z-50 mt-1">{list}</div>
      ) : null}
      {open && props.floatPanel && panelPos && typeof document !== "undefined"
        ? createPortal(
            <div
              id="theme-move-popover-portal"
              className="fixed z-[200]"
              style={{ top: panelPos.top, left: panelPos.left }}
            >
              {list}
            </div>,
            document.body
          )
        : null}
    </div>
  );
}

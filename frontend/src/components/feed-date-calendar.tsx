"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { todayIsoDate } from "@/lib/today-iso-date";
import type { Locale } from "@/lib/types";

const WEEKDAYS_ZH = ["一", "二", "三", "四", "五", "六", "日"];
const WEEKDAYS_EN = ["M", "T", "W", "T", "F", "S", "S"];
const PANEL_ID = "feed-date-picker-portal";

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function addMonths(d: Date, delta: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + delta, 1);
}

function isoFromParts(year: number, month: number, day: number): string {
  const m = String(month + 1).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${m}-${dd}`;
}

type FeedDateCalendarPanelProps = {
  locale: Locale;
  month: Date;
  selectedDate: string | null;
  dayCounts: Map<string, number>;
  onMonthChange: (month: Date) => void;
  onSelectDate: (date: string | null) => void;
  labels: {
    clear: string;
    today: string;
  };
};

function FeedDateCalendarPanel(props: FeedDateCalendarPanelProps): JSX.Element {
  const { locale, month, selectedDate, dayCounts, onMonthChange, onSelectDate, labels } = props;
  const today = todayIsoDate();

  const cells = useMemo(() => {
    const first = startOfMonth(month);
    const year = first.getFullYear();
    const mon = first.getMonth();
    const daysInMonth = new Date(year, mon + 1, 0).getDate();
    const offset = (first.getDay() + 6) % 7;
    const grid: Array<{ date: string | null; day: number | null }> = [];
    for (let i = 0; i < offset; i += 1) {
      grid.push({ date: null, day: null });
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      grid.push({ date: isoFromParts(year, mon, day), day });
    }
    return grid;
  }, [month]);

  const monthLabel =
    locale === "zh"
      ? `${month.getFullYear()}年${month.getMonth() + 1}月`
      : month.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  const weekdays = locale === "zh" ? WEEKDAYS_ZH : WEEKDAYS_EN;

  return (
    <div className="w-[17.5rem] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onMonthChange(addMonths(month, -1))}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground"
            aria-label={locale === "zh" ? "上个月" : "Previous month"}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[6.5rem] text-center text-sm font-medium">{monthLabel}</span>
          <button
            type="button"
            onClick={() => onMonthChange(addMonths(month, 1))}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-soft hover:text-foreground"
            aria-label={locale === "zh" ? "下个月" : "Next month"}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onSelectDate(today)}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-soft"
          >
            {labels.today}
          </button>
          <button
            type="button"
            onClick={() => onSelectDate(null)}
            disabled={!selectedDate}
            className="rounded border border-border px-2 py-0.5 text-xs hover:bg-soft disabled:opacity-40"
          >
            {labels.clear}
          </button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px] text-muted">
        {weekdays.map((wd, i) => (
          <div key={`${wd}-${i}`} className="py-0.5">
            {wd}
          </div>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-7 gap-1">
        {cells.map((cell, index) => {
          if (!cell.date || cell.day === null) {
            return <div key={`empty-${index}`} className="h-8" />;
          }
          const count = dayCounts.get(cell.date) ?? 0;
          const isSelected = selectedDate === cell.date;
          const isToday = cell.date === today;
          const isFuture = cell.date > today;
          return (
            <button
              key={cell.date}
              type="button"
              disabled={isFuture}
              onClick={() => onSelectDate(cell.date)}
              className={`flex h-8 flex-col items-center justify-center rounded-md text-xs transition-colors ${
                isSelected
                  ? "bg-accent text-accent-foreground"
                  : isToday
                    ? "ring-1 ring-accent/60 hover:bg-soft"
                    : count > 0
                      ? "hover:bg-soft"
                      : "text-muted hover:bg-soft"
              } ${isFuture ? "cursor-not-allowed opacity-30" : ""}`}
            >
              <span className="leading-none">{cell.day}</span>
              {count > 0 ? (
                <span
                  className={`mt-0.5 text-[9px] leading-none tabular-nums ${
                    isSelected ? "text-accent-foreground/80" : "text-muted"
                  }`}
                >
                  {count > 99 ? "99+" : count}
                </span>
              ) : (
                <span className="mt-0.5 h-1.5" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export type FeedDatePickerProps = FeedDateCalendarPanelProps & {
  ariaLabel: string;
};

export function FeedDatePicker(props: FeedDatePickerProps): JSX.Element {
  const { ariaLabel, onSelectDate, ...panelProps } = props;
  const [open, setOpen] = useState(false);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const panelWidth = 280;
    const panelHeight = 320;
    const gap = 6;
    let left = rect.right - panelWidth;
    let top = rect.bottom + gap;
    if (left < 8) {
      left = 8;
    }
    if (left + panelWidth > window.innerWidth - 8) {
      left = window.innerWidth - panelWidth - 8;
    }
    if (top + panelHeight > window.innerHeight - 8) {
      top = rect.top - panelHeight - gap;
    }
    setPanelPos({ top, left });
  }, [open, panelProps.month]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onDocClick(event: MouseEvent): void {
      const target = event.target as Node;
      if (wrapRef.current?.contains(target)) {
        return;
      }
      const portal = document.getElementById(PANEL_ID);
      if (portal?.contains(target)) {
        return;
      }
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function handleSelect(date: string | null): void {
    onSelectDate(date);
    setOpen(false);
  }

  const active = Boolean(panelProps.selectedDate);

  const panel =
    open && panelPos
      ? createPortal(
          <div
            id={PANEL_ID}
            className="fixed z-[200] rounded-lg border border-border bg-surface shadow-xl"
            style={{ top: panelPos.top, left: panelPos.left }}
          >
            <FeedDateCalendarPanel {...panelProps} onSelectDate={handleSelect} />
          </div>,
          document.body
        )
      : null;

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        title={ariaLabel}
        aria-label={ariaLabel}
        aria-expanded={open}
        className={`flex h-8 w-8 items-center justify-center rounded-md border transition-colors ${
          active
            ? "border-accent/50 bg-accent/10 text-accent"
            : "border-transparent text-muted hover:border-border hover:bg-soft hover:text-foreground"
        }`}
      >
        <CalendarDays className="h-4 w-4" />
      </button>
      {panel}
    </div>
  );
}

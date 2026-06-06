"use client";

import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Snowflake,
  X
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type FullSyncStatus } from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";

const COLLAPSED_KEY = "on1y-cold-start-panel-collapsed";
const DISMISSED_KEY = "on1y-cold-start-panel-dismissed";

type ColdStartEvent = {
  id: number;
  kind: string;
  status: string;
  phase: string;
  title: string;
  platform?: string | null;
};

function formatMs(ms: number | undefined): string {
  const value = ms ?? 0;
  if (value > 0 && value < 1000) {
    return "<1s";
  }
  const totalS = Math.max(0, Math.floor(value / 1000));
  if (totalS < 60) {
    return `${totalS}s`;
  }
  const m = Math.floor(totalS / 60);
  const s = totalS % 60;
  return `${m}m${String(s).padStart(2, "0")}s`;
}

function phaseLabel(phase: string | null | undefined, ui: (key: UiKey) => string): string {
  if (phase === "collections") {
    return ui("coldStartPhaseCollections");
  }
  if (phase === "subscriptions") {
    return ui("coldStartPhaseSubscriptions");
  }
  if (phase === "pipeline") {
    return ui("coldStartPhaseIngest");
  }
  if (phase === "done") {
    return ui("coldStartIngestDone");
  }
  return ui("coldStartRunning");
}

export function ColdStartFloatingPanel(props: {
  locale: Locale;
  status: FullSyncStatus | null;
  onDismiss?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [collapsed, setCollapsed] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const wasActiveRef = useRef(false);

  const ingestRunning = Boolean(props.status?.running);
  const bg = props.status?.background_distill;
  const distillRunning = Boolean(bg?.running);
  const active = ingestRunning || distillRunning;

  useEffect(() => {
    try {
      setCollapsed(sessionStorage.getItem(COLLAPSED_KEY) === "1");
      setDismissed(sessionStorage.getItem(DISMISSED_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (active) {
      wasActiveRef.current = true;
      try {
        sessionStorage.removeItem(DISMISSED_KEY);
      } catch {
        /* ignore */
      }
      setDismissed(false);
    }
  }, [active]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((value) => {
      const next = !value;
      try {
        sessionStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const dismiss = useCallback(() => {
    setDismissed(true);
    try {
      sessionStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* ignore */
    }
    props.onDismiss?.();
  }, [props]);

  const progress = props.status?.progress;
  const counters = progress?.counters ?? {};
  const ingested = counters.ingested ?? 0;
  const failed = counters.failed ?? 0;
  const distilledBg = typeof bg?.distilled === "number" ? bg.distilled : 0;
  const remainingBg = typeof bg?.remaining === "number" ? bg.remaining : null;

  const itemEvents = useMemo(() => {
    const events = progress?.events ?? [];
    return events
      .filter((e) => e.kind === "item" || e.kind === "error")
      .slice(-6) as ColdStartEvent[];
  }, [progress?.events]);

  const elapsedMs =
    props.status?.elapsed_ms ??
    progress?.elapsed_ms ??
    (props.status?.started_at && ingestRunning
      ? Math.max(0, Date.now() - Date.parse(props.status.started_at))
      : undefined);

  const summary = useMemo(() => {
    if (ingestRunning) {
      return ui("coldStartFloatIngesting")
        .replace("{ingested}", String(ingested))
        .replace("{failed}", failed > 0 ? ` · ${failed} ${ui("coldStartCounterFailed")}` : "");
    }
    if (distillRunning) {
      const rem =
        remainingBg != null
          ? ui("coldStartFloatDistillRemaining").replace("{remaining}", String(remainingBg))
          : ui("coldStartPhaseBackgroundDistill");
      return ui("coldStartFloatDistilling")
        .replace("{done}", String(distilledBg))
        .replace("{detail}", rem);
    }
    if (props.status?.current_phase === "done" && !distillRunning) {
      return ui("coldStartIngestDone");
    }
    return ui("coldStartRunning");
  }, [
    distillRunning,
    distilledBg,
    failed,
    ingestRunning,
    ingested,
    props.status?.current_phase,
    remainingBg,
    ui
  ]);

  if (!active && dismissed) {
    return null;
  }
  if (!active && !wasActiveRef.current) {
    return null;
  }
  if (!active && wasActiveRef.current && dismissed) {
    return null;
  }

  const currentPhase = ingestRunning
    ? props.status?.current_phase
    : distillRunning
      ? "background_distill"
      : props.status?.current_phase;

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={toggleCollapsed}
        className="fixed bottom-4 right-4 z-[60] flex max-w-[min(20rem,calc(100vw-2rem))] items-center gap-2 rounded-full border border-sky-200 bg-white/95 px-3 py-2 text-left text-sm shadow-lg backdrop-blur hover:bg-sky-50"
      >
        {active ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-sky-600" />
        ) : (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
        )}
        <Snowflake className="h-3.5 w-3.5 shrink-0 text-sky-600" />
        <span className="min-w-0 truncate font-medium text-neutral-800">{summary}</span>
        <ChevronUp className="h-4 w-4 shrink-0 text-neutral-400" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-[60] w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-sky-200 bg-white/95 shadow-xl backdrop-blur">
      <div className="flex items-center gap-2 border-b border-sky-100 bg-sky-50/80 px-3 py-2">
        <Snowflake className="h-4 w-4 shrink-0 text-sky-600" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-neutral-900">{ui("coldStartTitle")}</div>
          <div className="truncate text-[11px] text-neutral-500">
            {ingestRunning
              ? phaseLabel(currentPhase, ui)
              : distillRunning
                ? ui("coldStartPhaseBackgroundDistill")
                : ui("coldStartDone")}
            {elapsedMs != null && ingestRunning ? ` · ${formatMs(elapsedMs)}` : ""}
          </div>
        </div>
        <button
          type="button"
          aria-label={ui("coldStartFloatCollapse")}
          onClick={toggleCollapsed}
          className="rounded p-1 text-neutral-400 hover:bg-white hover:text-neutral-700"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
        {!active ? (
          <button
            type="button"
            aria-label={ui("coldStartFloatClose")}
            onClick={dismiss}
            className="rounded p-1 text-neutral-400 hover:bg-white hover:text-neutral-700"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      <div className="space-y-2 px-3 py-2.5">
        {ingestRunning ? (
          <div className="flex flex-wrap gap-2 text-[11px]">
            {(["collections", "subscriptions", "pipeline"] as const).map((phase) => {
              const idx = ["collections", "subscriptions", "pipeline"].indexOf(
                props.status?.current_phase === "starting"
                  ? ""
                  : (props.status?.current_phase ?? "")
              );
              const phaseIdx = ["collections", "subscriptions", "pipeline"].indexOf(phase);
              const done = phaseIdx < idx || props.status?.current_phase === "done";
              const activePhase = props.status?.current_phase === phase;
              return (
                <span
                  key={phase}
                  className={`rounded-full px-2 py-0.5 ${
                    done
                      ? "bg-emerald-50 text-emerald-800"
                      : activePhase
                        ? "bg-sky-100 text-sky-800"
                        : "bg-neutral-100 text-neutral-500"
                  }`}
                >
                  {phaseLabel(phase, ui)}
                </span>
              );
            })}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-neutral-50 px-2 py-1.5">
            <div className="text-[10px] text-neutral-500">{ui("coldStartCounterIngested")}</div>
            <div className="font-semibold tabular-nums text-neutral-900">{ingested}</div>
          </div>
          <div className="rounded-lg bg-neutral-50 px-2 py-1.5">
            <div className="text-[10px] text-neutral-500">{ui("coldStartCounterDistilled")}</div>
            <div className="font-semibold tabular-nums text-neutral-900">
              {distillRunning || distilledBg > 0 ? distilledBg : (counters.distilled ?? 0)}
              {remainingBg != null && distillRunning ? (
                <span className="ml-1 text-[10px] font-normal text-neutral-500">
                  / {remainingBg + distilledBg}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {props.status?.error ? (
          <div className="flex gap-2 rounded-lg bg-red-50 px-2 py-1.5 text-xs text-red-800">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{props.status.error}</span>
          </div>
        ) : null}

        {bg?.error ? (
          <div className="flex gap-2 rounded-lg bg-red-50 px-2 py-1.5 text-xs text-red-800">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{String(bg.error)}</span>
          </div>
        ) : null}

        {!ingestRunning && distillRunning ? (
          <p className="text-[11px] leading-relaxed text-neutral-500">{ui("coldStartFloatDistillHint")}</p>
        ) : null}

        {itemEvents.length > 0 && ingestRunning ? (
          <div className="max-h-28 space-y-1 overflow-y-auto border-t border-neutral-100 pt-2">
            {itemEvents.map((event) => (
              <div key={event.id} className="flex items-start gap-1.5 text-[11px] text-neutral-600">
                {event.status === "failed" ? (
                  <AlertCircle className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" />
                )}
                <span className="line-clamp-1">{event.title}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

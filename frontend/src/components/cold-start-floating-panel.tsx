"use client";

import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
  X
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type FullSyncStatus, type PipelineBarMetrics } from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";
import { platformLabel } from "@/lib/platform-label";

const COLLAPSED_KEY = "on1y-cold-start-panel-collapsed";
const DISMISSED_KEY = "on1y-cold-start-panel-dismissed";
const RECENT_EVENT_LIMIT = 3;

type RecentEvent = {
  id: number;
  kind: string;
  status: string;
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

function panelTitle(status: FullSyncStatus | null, ui: (key: UiKey) => string): string {
  if (status?.sync_kind === "auto") {
    return ui("syncActivityAuto");
  }
  if (status?.sync_kind === "subscription") {
    return ui("syncActivityTitle");
  }
  if (status?.resident_panel && !status?.running) {
    return ui("syncActivityTitle");
  }
  return ui("coldStartTitle");
}

function waitingPollMinutes(
  scheduler: FullSyncStatus["auto_sync_scheduler"],
  nowMs: number
): number | null {
  const iso = scheduler?.next_subscription_tick_at;
  if (!iso) {
    return null;
  }
  const target = Date.parse(iso);
  if (!Number.isFinite(target) || target <= nowMs) {
    return null;
  }
  const minutes = Math.ceil((target - nowMs) / 60_000);
  return Math.max(1, minutes);
}

function formatLastSync(iso: string | null | undefined, locale: Locale): string {
  if (!iso) {
    return "—";
  }
  try {
    const d = new Date(iso);
    return d.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}

function formatBarFraction(bar: PipelineBarMetrics): string {
  return `${bar.done}/${bar.total}`;
}

function eventStatusLabel(status: string, ui: (key: UiKey) => string): string {
  const map: Record<string, UiKey> = {
    enqueued: "coldStartStatusEnqueued",
    ingested: "coldStartStatusIngested",
    distilled: "coldStartStatusDistilled",
    failed: "coldStartStatusFailed",
    skipped: "coldStartStatusSkipped"
  };
  const key = map[status];
  return key ? ui(key) : status;
}

function eventStatusTone(status: string): string {
  if (status === "failed") {
    return "bg-red-950/30 text-red-300";
  }
  if (status === "distilled") {
    return "bg-accent-soft text-highlight";
  }
  if (status === "ingested" || status === "enqueued") {
    return "bg-soft text-muted";
  }
  return "bg-panel text-muted";
}

function RecentEventRow(props: {
  event: RecentEvent;
  locale: Locale;
  ui: (key: UiKey) => string;
}): JSX.Element {
  const { event, locale, ui } = props;
  return (
    <div className="group flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-soft/80">
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          event.status === "failed"
            ? "bg-red-400/80"
            : event.status === "distilled"
              ? "bg-highlight"
              : "bg-progress"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] font-medium text-foreground">{event.title}</div>
        {event.platform ? (
          <div className="truncate text-[10px] text-muted">
            {platformLabel(event.platform, locale)}
          </div>
        ) : null}
      </div>
      <span
        className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${eventStatusTone(event.status)}`}
      >
        {eventStatusLabel(event.status, ui)}
      </span>
    </div>
  );
}

function PipelineBarRow(props: {
  label: string;
  bar: PipelineBarMetrics;
  active?: boolean;
}): JSX.Element {
  const { bar, label, active } = props;
  const pct = bar.total > 0 ? Math.min(100, (bar.done / bar.total) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-7 shrink-0 text-muted">{label}</span>
      <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-soft">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            active ? "bg-progress" : bar.done >= bar.total && bar.total > 0 ? "bg-highlight" : "bg-accent"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-14 shrink-0 text-right tabular-nums text-foreground">
        {formatBarFraction(bar)}
      </span>
    </div>
  );
}

export function ColdStartFloatingPanel(props: {
  locale: Locale;
  status: FullSyncStatus | null;
  onDismiss?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [collapsed, setCollapsed] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const wasActiveRef = useRef(false);

  const fullSyncRunning = Boolean(props.status?.running);
  const subSyncRunning = Boolean(props.status?.subscription_sync?.running);
  const ingestRunning = fullSyncRunning || subSyncRunning;
  const bg = props.status?.background_distill;
  const distillRunning = Boolean(bg?.running);
  const active = Boolean(props.status?.active) || ingestRunning || distillRunning;
  const resident = Boolean(props.status?.resident_panel);
  const pendingWork = Boolean(props.status?.pending_work);
  const catchUp = Boolean(props.status?.subscription_sync?.backfill);

  useEffect(() => {
    try {
      setCollapsed(sessionStorage.getItem(COLLAPSED_KEY) === "1");
      setDismissed(sessionStorage.getItem(DISMISSED_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!props.status?.auto_sync_scheduler?.next_subscription_tick_at || active) {
      return;
    }
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [active, props.status?.auto_sync_scheduler?.next_subscription_tick_at]);

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

  const bars = useMemo(() => {
    const fromApi = props.status?.pipeline_bars;
    const fallbackIngestTotal = Math.max(
      counters.ingested ?? 0,
      counters.enqueued ?? 0
    );
    const fallbackIngest: PipelineBarMetrics = {
      done: counters.ingested ?? 0,
      total: fallbackIngestTotal
    };
    const fallbackDistill: PipelineBarMetrics = {
      done: counters.distilled ?? (typeof bg?.distilled === "number" ? bg.distilled : 0),
      total:
        typeof bg?.remaining === "number" && typeof bg?.distilled === "number"
          ? bg.distilled + bg.remaining
          : counters.distilled ?? 0
    };
    return {
      ingest: fromApi?.ingest ?? fallbackIngest,
      subtitles: fromApi?.subtitles ?? { done: 0, total: 0 },
      distill: fromApi?.distill ?? fallbackDistill
    };
  }, [bg?.distilled, bg?.remaining, counters.distilled, counters.enqueued, counters.ingested, props.status?.pipeline_bars]);

  const recentEvents = useMemo(() => {
    const events = progress?.events ?? [];
    return events
      .filter((e) => e.kind === "item" || e.kind === "error")
      .slice(-RECENT_EVENT_LIMIT)
      .reverse() as RecentEvent[];
  }, [progress?.events]);

  const elapsedMs =
    props.status?.elapsed_ms ??
    progress?.elapsed_ms ??
    (props.status?.started_at && ingestRunning
      ? Math.max(0, Date.now() - Date.parse(props.status.started_at))
      : undefined);

  const barsSummary = `${formatBarFraction(bars.ingest)} · ${formatBarFraction(bars.subtitles)} · ${formatBarFraction(bars.distill)}`;

  const shouldShow = active || resident || pendingWork || wasActiveRef.current;
  if (!shouldShow || (!active && dismissed && !resident)) {
    return null;
  }

  const currentPhase = ingestRunning
    ? props.status?.current_phase
    : distillRunning
      ? "background_distill"
      : props.status?.current_phase;

  const subtitle = (() => {
    if (ingestRunning) {
      return phaseLabel(currentPhase, ui);
    }
    if (distillRunning) {
      return ui("coldStartPhaseBackgroundDistill");
    }
    if (active) {
      return ui("coldStartDone");
    }
    const waitMinutes = waitingPollMinutes(props.status?.auto_sync_scheduler, nowMs);
    if (waitMinutes != null) {
      return ui("syncActivityWaitingPoll").replace("{minutes}", String(waitMinutes));
    }
    const parts: string[] = [ui("syncActivityIdle")];
    if (catchUp) {
      parts.push(ui("syncActivityCatchUp"));
    }
    if (pendingWork) {
      parts.push(ui("syncActivityPending"));
    }
    if (props.status?.last_auto_sync_at) {
      parts.push(
        ui("syncActivityLastSync").replace(
          "{time}",
          formatLastSync(props.status.last_auto_sync_at, props.locale)
        )
      );
    }
    return parts.join(" · ");
  })();

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={toggleCollapsed}
        className="fixed bottom-4 right-4 z-[60] flex max-w-[min(24rem,calc(100vw-2rem))] items-center gap-2 rounded-full border border-border bg-surface/95 px-3 py-2 text-left text-sm shadow-on1y backdrop-blur-md hover:bg-soft/80"
      >
        {active ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-highlight" />
        ) : (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-highlight" />
        )}
        <RefreshCw className="h-3.5 w-3.5 shrink-0 text-highlight" />
        <span className="min-w-0 truncate font-medium tabular-nums text-foreground">
          {active ? barsSummary : panelTitle(props.status, ui)}
        </span>
        <ChevronUp className="h-4 w-4 shrink-0 text-muted" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-[60] w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-surface/95 shadow-on1y backdrop-blur-md">
      <div className="flex items-center gap-2 border-b border-border bg-panel/90 px-3 py-2">
        <RefreshCw className="h-4 w-4 shrink-0 text-highlight" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">
            {panelTitle(props.status, ui)}
          </div>
          <div className="truncate text-[11px] text-muted">
            {subtitle}
            {elapsedMs != null && ingestRunning ? ` · ${formatMs(elapsedMs)}` : ""}
          </div>
        </div>
        <button
          type="button"
          aria-label={ui("coldStartFloatCollapse")}
          onClick={toggleCollapsed}
          className="rounded p-1 text-muted hover:bg-soft hover:text-foreground"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
        {!active && !resident ? (
          <button
            type="button"
            aria-label={ui("coldStartFloatClose")}
            onClick={dismiss}
            className="rounded p-1 text-muted hover:bg-soft hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      <div className="space-y-2 px-3 py-2.5">
        {fullSyncRunning || subSyncRunning ? (
          <div className="flex flex-wrap gap-2 text-[11px]">
            {(fullSyncRunning
              ? (["collections", "subscriptions", "pipeline"] as const)
              : (["subscriptions", "pipeline"] as const)
            ).map((phase) => {
              const phaseOrder = fullSyncRunning
                ? ["collections", "subscriptions", "pipeline"]
                : ["subscriptions", "pipeline"];
              const idx = phaseOrder.indexOf(
                props.status?.current_phase === "starting"
                  ? ""
                  : (props.status?.current_phase ?? "")
              );
              const phaseIdx = phaseOrder.indexOf(phase);
              const done = phaseIdx < idx || props.status?.current_phase === "done";
              const activePhase = props.status?.current_phase === phase;
              return (
                <span
                  key={phase}
                  className={`rounded-full px-2 py-0.5 ${
                    done
                      ? "bg-accent-soft text-highlight"
                      : activePhase
                        ? "bg-soft text-foreground"
                        : "bg-panel text-muted"
                  }`}
                >
                  {phaseLabel(phase, ui)}
                </span>
              );
            })}
          </div>
        ) : null}

        <div className="space-y-1.5">
          <PipelineBarRow
            label={ui("coldStartBarIngest")}
            bar={bars.ingest}
            active={ingestRunning || subSyncRunning}
          />
          <PipelineBarRow
            label={ui("coldStartBarSubtitles")}
            bar={bars.subtitles}
            active={ingestRunning || subSyncRunning}
          />
          <PipelineBarRow
            label={ui("coldStartBarDistill")}
            bar={bars.distill}
            active={ingestRunning || subSyncRunning || distillRunning}
          />
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
          <p className="text-[11px] leading-relaxed text-muted">{ui("coldStartFloatDistillHint")}</p>
        ) : null}

        {active && recentEvents.length > 0 ? (
          <div className="border-t border-border pt-2">
            <div className="mb-1 px-1.5 text-[10px] font-medium uppercase tracking-wide text-muted">
              {ui("coldStartFloatRecent")}
            </div>
            <div className="space-y-0.5">
              {recentEvents.map((event) => (
                <RecentEventRow key={event.id} event={event} locale={props.locale} ui={ui} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

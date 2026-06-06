"use client";

import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Circle,
  Loader2,
  Snowflake
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getFullSyncStatus,
  runFullSync,
  type FullSyncStatus,
  type FullSyncTiming
} from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";
import { loadStoredLocale } from "@/lib/locale-preference";
import { platformLabel } from "@/lib/platform-label";

type ColdStartEvent = {
  id: number;
  ts: string;
  kind: string;
  status: string;
  phase: string;
  title: string;
  platform?: string | null;
  detail?: string | null;
  url?: string | null;
};

type ColdStartProgress = {
  phase?: string | null;
  elapsed_ms?: number;
  counters?: Record<string, number>;
  events?: ColdStartEvent[];
  event_total?: number;
};

const PHASES = ["collections", "subscriptions", "pipeline"] as const;

function formatMs(ms: number | undefined): string {
  const value = ms ?? 0;
  if (value > 0 && value < 1000) {
    return "<1s";
  }
  const totalS = Math.max(0, Math.floor(value / 1000));
  if (totalS < 1) {
    return "0s";
  }
  if (totalS < 60) {
    return `${totalS}s`;
  }
  const m = Math.floor(totalS / 60);
  const s = totalS % 60;
  return `${m}m${String(s).padStart(2, "0")}s`;
}

function phaseIndex(phase: string | null | undefined): number {
  if (!phase || phase === "starting") {
    return -1;
  }
  if (phase === "done") {
    return PHASES.length;
  }
  const idx = PHASES.indexOf(phase as (typeof PHASES)[number]);
  return idx >= 0 ? idx : -1;
}

function statusIcon(status: string, kind?: string): JSX.Element {
  if (kind === "step") {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-sky-600" />;
  }
  if (status === "distilled" || status === "ingested" || status === "enqueued") {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />;
  }
  if (status === "failed") {
    return <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />;
  }
  if (status === "ingesting" || status === "distilling" || status === "active") {
    return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-neutral-500" />;
  }
  return <Circle className="h-4 w-4 shrink-0 text-neutral-300" />;
}

function eventStatusLabel(status: string, ui: (key: UiKey) => string): string {
  const map: Record<string, UiKey> = {
    enqueued: "coldStartStatusEnqueued",
    ingesting: "coldStartStatusIngesting",
    ingested: "coldStartStatusIngested",
    distilling: "coldStartStatusDistilling",
    distilled: "coldStartStatusDistilled",
    failed: "coldStartStatusFailed",
    skipped: "coldStartStatusSkipped"
  };
  const key = map[status];
  return key ? ui(key) : status;
}

export function ColdStartScreen(props: { autoStart?: boolean }): JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const autoStart = props.autoStart ?? searchParams.get("start") === "1";
  const [locale] = useState<Locale>(() => loadStoredLocale());
  const ui = (key: UiKey): string => t(locale, key);

  const [status, setStatus] = useState<FullSyncStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(0);
  const autoStartedRef = useRef(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  const progress = (status?.progress ?? null) as ColdStartProgress | null;
  const timing = (status?.last_timing ?? null) as FullSyncTiming | null;
  const activePhaseIdx = phaseIndex(status?.current_phase);
  const running = Boolean(status?.running) || starting;
  const done =
    !Boolean(status?.running) &&
    !starting &&
    (status?.current_phase === "done" || Boolean(timing));

  const itemEvents = useMemo(() => {
    const events = progress?.events ?? [];
    return events.filter((e) => e.kind === "item" || e.kind === "error" || e.kind === "step");
  }, [progress?.events]);

  const applyStatus = useCallback((next: FullSyncStatus) => {
    setStatus(next);
    if (next.error) {
      setError(next.error);
    }
  }, []);

  const poll = useCallback(async () => {
    const next = await getFullSyncStatus();
    applyStatus(next);
    return next;
  }, [applyStatus]);

  const startColdStart = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const result = await runFullSync();
      if (!result.started) {
        setError(result.message);
        await poll();
        return;
      }
      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }, [poll]);

  useEffect(() => {
    void poll().then((initial) => {
      if (autoStart && !autoStartedRef.current && !initial.running) {
        autoStartedRef.current = true;
        void startColdStart();
      }
    });
  }, [autoStart, poll, startColdStart]);

  useEffect(() => {
    if (!Boolean(status?.running)) {
      return;
    }
    const timer = window.setInterval(() => {
      void poll();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [status?.running, poll]);

  useEffect(() => {
    if (!Boolean(status?.running) && !starting) {
      return;
    }
    const timer = window.setInterval(() => {
      setClock((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [status?.running, starting]);

  useEffect(() => {
    const node = listRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [itemEvents.length]);

  const elapsedMs = useMemo(() => {
    void clock;
    const fromApi = (status as { elapsed_ms?: number } | null)?.elapsed_ms ?? progress?.elapsed_ms;
    if (status?.started_at && (Boolean(status.running) || starting)) {
      const started = Date.parse(status.started_at);
      if (!Number.isNaN(started)) {
        return Math.max(0, Date.now() - started);
      }
    }
    return fromApi;
  }, [clock, progress?.elapsed_ms, starting, status]);

  const elapsed = done
    ? timing?.total_human ?? formatMs(elapsedMs)
    : formatMs(elapsedMs);

  const showSlowHint =
    Boolean(status?.running) &&
    (elapsedMs ?? 0) > 30_000 &&
    itemEvents.length === 0;

  return (
    <div className="flex min-h-screen flex-col bg-[#f7f7f5] text-neutral-900">
      <header className="border-b border-neutral-200/80 bg-white px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-600 hover:bg-neutral-50"
            >
              <ArrowLeft className="h-4 w-4" />
              {ui("coldStartBack")}
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Snowflake className="h-5 w-5 text-sky-600" />
                <h1 className="truncate text-lg font-semibold">{ui("coldStartTitle")}</h1>
              </div>
              <p className="mt-0.5 truncate text-xs text-neutral-500">{ui("coldStartSubtitle")}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {Boolean(status?.running) ? (
              <button
                type="button"
                onClick={() => router.push("/")}
                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-800 hover:bg-neutral-50"
              >
                {ui("coldStartBrowseWhileRunning")}
              </button>
            ) : null}
            <div className="text-right">
            <div className="text-xs text-neutral-500">{ui("coldStartElapsed")}</div>
            <div className="font-mono text-lg font-semibold tabular-nums">{elapsed}</div>
            {Boolean(status?.running) && status?.current_phase ? (
              <div className="mt-0.5 text-[11px] text-sky-600">
                {ui(
                  status.current_phase === "collections"
                    ? "coldStartPhaseCollections"
                    : status.current_phase === "subscriptions"
                      ? "coldStartPhaseSubscriptions"
                      : status.current_phase === "pipeline"
                        ? "coldStartPhasePipeline"
                        : "coldStartRunning"
                )}
              </div>
            ) : null}
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 px-4 py-5 sm:px-6">
        <p className="text-xs text-neutral-500">{ui("coldStartCollectionsNote")}</p>

        <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
          <div className="grid gap-3 sm:grid-cols-3">
            {PHASES.map((phase, index) => {
              const active = activePhaseIdx === index;
              const complete = activePhaseIdx > index || done;
              const phaseKey =
                phase === "collections"
                  ? "coldStartPhaseCollections"
                  : phase === "subscriptions"
                    ? "coldStartPhaseSubscriptions"
                    : "coldStartPhasePipeline";
              const ms = status?.phases_ms?.[phase];
              return (
                <div
                  key={phase}
                  className={`rounded-lg border px-3 py-3 transition ${
                    active
                      ? "border-sky-300 bg-sky-50"
                      : complete
                        ? "border-emerald-200 bg-emerald-50/60"
                        : "border-neutral-100 bg-neutral-50"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {active && running ? (
                      <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
                    ) : complete ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    ) : (
                      <Circle className="h-4 w-4 text-neutral-300" />
                    )}
                    <span className="text-sm font-medium">{ui(phaseKey)}</span>
                  </div>
                  <div className="mt-1 pl-6 text-xs text-neutral-500">
                    {ms ? formatMs(ms) : active && running ? ui("coldStartRunning") : "—"}
                  </div>
                </div>
              );
            })}
          </div>

          {progress?.counters ? (
            <div className="mt-4 grid grid-cols-2 gap-2 border-t border-neutral-100 pt-4 text-center sm:grid-cols-4">
              {(
                [
                  ["enqueued", "coldStartCounterEnqueued"],
                  ["ingested", "coldStartCounterIngested"],
                  ["distilled", "coldStartCounterDistilled"],
                  ["failed", "coldStartCounterFailed"]
                ] as const
              ).map(([key, labelKey]) => (
                <div key={key} className="rounded-md bg-neutral-50 px-2 py-2">
                  <div className="text-lg font-semibold tabular-nums">
                    {progress.counters?.[key] ?? 0}
                  </div>
                  <div className="text-[11px] text-neutral-500">{ui(labelKey)}</div>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        {showSlowHint ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {ui("coldStartSlowHint")}
          </div>
        ) : null}

        {!Boolean(status?.running) && !done && !starting ? (
          <section className="rounded-xl border border-dashed border-neutral-300 bg-white p-6 text-center">
            <p className="text-sm text-neutral-600">{ui("coldStartIntro")}</p>
            <button
              type="button"
              disabled={starting}
              onClick={() => void startColdStart()}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-black px-5 py-2.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Snowflake className="h-4 w-4" />}
              {starting ? ui("coldStartStarting") : ui("coldStartStart")}
            </button>
          </section>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
            <h2 className="text-sm font-semibold">{ui("coldStartActivity")}</h2>
            <span className="text-xs text-neutral-400">
              {progress?.event_total ?? itemEvents.length} {ui("coldStartEvents")}
            </span>
          </div>
          <div ref={listRef} className="min-h-[280px] flex-1 overflow-y-auto px-2 py-2 scrollbar-thin">
            {itemEvents.length === 0 ? (
              <div className="flex h-full items-center justify-center px-4 py-12 text-sm text-neutral-400">
                {running ? ui("coldStartWaitingEvents") : ui("coldStartNoEvents")}
              </div>
            ) : (
              <ul className="space-y-1">
                {itemEvents.map((event) => (
                  <li
                    key={event.id}
                    className="flex items-start gap-2 rounded-md px-2 py-2 hover:bg-neutral-50"
                  >
                    {statusIcon(event.status, event.kind)}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="truncate text-sm font-medium text-neutral-900">
                          {event.title}
                        </span>
                        {event.platform ? (
                          <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-600">
                            {platformLabel(event.platform, locale)}
                          </span>
                        ) : null}
                        <span className="text-[11px] text-neutral-400">
                          {eventStatusLabel(event.status, ui)}
                        </span>
                      </div>
                      {event.detail ? (
                        <p className="mt-0.5 truncate text-xs text-neutral-500">{event.detail}</p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {done ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4">
            <div>
              <div className="font-medium text-emerald-900">{ui("coldStartDone")}</div>
              {timing ? (
                <div className="mt-1 text-sm text-emerald-800">
                  {ui("coldStartTiming")
                    .replace("{total}", timing.total_human)
                    .replace("{collections}", timing.phases_human.collections ?? "—")
                    .replace("{subscriptions}", timing.phases_human.subscriptions ?? "—")
                    .replace("{pipeline}", timing.phases_human.pipeline ?? "—")}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => router.push("/")}
              className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800"
            >
              {ui("coldStartBackWorkbench")}
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}

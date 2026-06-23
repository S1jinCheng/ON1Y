"use client";

import { Plus, Settings2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getSubscriptionSettings,
  getSubscriptionSyncStatus,
  runSubscriptionSync,
  saveSubscriptionSettings,
  type SubscriptionSettings,
  type SubscriptionSyncStatus
} from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";

type PlatformKey = "bilibili" | "youtube" | "zhihu" | "twitter";

const ALL_PLATFORMS: PlatformKey[] = ["bilibili", "youtube", "zhihu", "twitter"];

function platformLabel(platform: PlatformKey, ui: (key: UiKey) => string): string {
  if (platform === "bilibili") {
    return ui("platformBilibili");
  }
  if (platform === "youtube") {
    return ui("platformYoutube");
  }
  if (platform === "twitter") {
    return "X / Twitter";
  }
  return ui("platformZhihu");
}

function pickDisplayDate(settings: SubscriptionSettings): string {
  const dates = ALL_PLATFORMS.map((p) => {
    if (p === "bilibili") {
      return settings.bilibili_sync_since;
    }
    if (p === "youtube") {
      return settings.youtube_sync_since;
    }
    if (p === "twitter") {
      return settings.twitter_sync_since;
    }
    return settings.zhihu_sync_since;
  }).filter((value): value is string => Boolean(value));
  if (dates.length === 0) {
    return "";
  }
  return dates[0] ?? "";
}

function buildSincePayload(
  active: PlatformKey[],
  syncSince: string
): {
  bilibili_sync_since?: string | null;
  youtube_sync_since?: string | null;
  zhihu_sync_since?: string | null;
  twitter_sync_since?: string | null;
} {
  const since = syncSince.trim();
  const payload: {
    bilibili_sync_since?: string | null;
    youtube_sync_since?: string | null;
    zhihu_sync_since?: string | null;
    twitter_sync_since?: string | null;
  } = {};
  if (active.includes("bilibili")) {
    payload.bilibili_sync_since = since || "";
  }
  if (active.includes("youtube")) {
    payload.youtube_sync_since = since || "";
  }
  if (active.includes("zhihu")) {
    payload.zhihu_sync_since = since || "";
  }
  if (active.includes("twitter")) {
    payload.twitter_sync_since = since || "";
  }
  return payload;
}

function sumEnqueued(status: SubscriptionSyncStatus): number {
  const report = status.last_report;
  if (!report) {
    return 0;
  }
  let total = 0;
  for (const key of ALL_PLATFORMS) {
    const block = report[key] as { poll?: { enqueued?: number } } | undefined;
    total += block?.poll?.enqueued ?? 0;
  }
  return total;
}

function sumDistilled(status: SubscriptionSyncStatus): number {
  const report = status.last_report;
  if (!report) {
    return 0;
  }
  let total = 0;
  for (const key of ALL_PLATFORMS) {
    const block = report[key] as
      | {
          enrich?: { distill?: { distilled?: number } };
          distill?: { distilled?: number };
        }
      | undefined;
    total += block?.enrich?.distill?.distilled ?? block?.distill?.distilled ?? 0;
  }
  return total;
}

function pollSyncUntilDone(onMessage: (message: string) => void, ui: (key: UiKey) => string): void {
  const timer = window.setInterval(() => {
    void (async () => {
      try {
        const status = await getSubscriptionSyncStatus();
        if (status.running) {
          return;
        }
        window.clearInterval(timer);
        if (status.error) {
          onMessage(status.error);
          return;
        }
        const enqueued = sumEnqueued(status);
        const distilled = sumDistilled(status);
        let message = `${ui("syncDone")}: +${enqueued}`;
        if (distilled > 0) {
          message += ` · ${ui("syncSummariesDone")} ${distilled}`;
        }
        onMessage(message);
      } catch (error) {
        window.clearInterval(timer);
        onMessage(error instanceof Error ? error.message : String(error));
      }
    })();
  }, 3000);
}

export function SubscriptionSettingsPanel(props: {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  onMessage?: (message: string) => void;
  onSyncStarted?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activePlatforms, setActivePlatforms] = useState<PlatformKey[]>([...ALL_PLATFORMS]);
  const [syncSince, setSyncSince] = useState("");
  const [useAiSummary, setUseAiSummary] = useState(true);

  const availableToAdd = ALL_PLATFORMS.filter((p) => !activePlatforms.includes(p));

  useEffect(() => {
    if (!props.open) {
      return;
    }
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const settings = await getSubscriptionSettings();
        if (cancelled) {
          return;
        }
        const enabled = (settings.enabled_platforms ?? ALL_PLATFORMS).filter((p) =>
          ALL_PLATFORMS.includes(p as PlatformKey)
        ) as PlatformKey[];
        setActivePlatforms(enabled.length > 0 ? enabled : [...ALL_PLATFORMS]);
        setSyncSince(pickDisplayDate(settings));
        setUseAiSummary(true);
      } catch (error) {
        props.onMessage?.(error instanceof Error ? error.message : String(error));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props.open, props.onMessage]);

  if (!props.open) {
    return null;
  }

  function removePlatform(platform: PlatformKey): void {
    setActivePlatforms((prev) => prev.filter((p) => p !== platform));
  }

  function addPlatform(platform: PlatformKey): void {
    setActivePlatforms((prev) => {
      if (prev.includes(platform)) {
        return prev;
      }
      return [...prev, platform].sort(
        (a, b) => ALL_PLATFORMS.indexOf(a) - ALL_PLATFORMS.indexOf(b)
      );
    });
  }

  async function persistSettings(platforms: PlatformKey[]): Promise<void> {
    const sinceFields = buildSincePayload(platforms, syncSince);
    await saveSubscriptionSettings({
      ...sinceFields,
      enabled_platforms: platforms
    });
  }

  async function handleSync(): Promise<void> {
    if (activePlatforms.length === 0) {
      props.onMessage?.(ui("selectAtLeastOnePlatform"));
      return;
    }
    setSubmitting(true);
    try {
      await persistSettings(activePlatforms);
      const result = await runSubscriptionSync({
        platforms: activePlatforms,
        ingest: true,
        use_ai_summary: useAiSummary,
        ingest_limit: 30,
        subtitle_limit: 30,
        distill_limit: useAiSummary ? 50 : 0
      });
      if (!result.started) {
        props.onMessage?.(result.message ?? ui("syncAlreadyRunning"));
        return;
      }
      props.onMessage?.(result.message ?? ui("syncStarted"));
      props.onSyncStarted?.();
      props.onClose();
    } catch (error) {
      props.onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/35 p-4 pt-12">
      <div
        role="dialog"
        aria-labelledby="subscription-settings-title"
        className="w-full max-w-sm rounded-xl border border-neutral-200 bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
          <h2 id="subscription-settings-title" className="text-sm font-semibold tracking-tight">
            {ui("subscriptionSettings")}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-neutral-400 hover:bg-neutral-100 hover:text-black"
            aria-label={ui("themeEditDone")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-4 py-4">
          <section>
            <p className="mb-2 text-xs font-medium text-neutral-500">{ui("syncPlatformBox")}</p>
            <div className="min-h-[7.5rem] rounded-lg border border-neutral-200 bg-neutral-50/80 p-2">
              {activePlatforms.length === 0 ? (
                <p className="px-2 py-6 text-center text-xs text-muted">{ui("syncPlatformEmpty")}</p>
              ) : (
                <ul className="space-y-1">
                  {activePlatforms.map((platform) => (
                    <li
                      key={platform}
                      className="flex items-center gap-2 rounded-md border border-neutral-200/80 bg-white px-2 py-2 shadow-sm"
                    >
                      <span
                        className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-neutral-300 bg-black"
                        aria-hidden
                      >
                        <span className="h-2 w-2 rounded-sm bg-white" />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-neutral-900">
                        {platformLabel(platform, ui)}
                      </span>
                      <button
                        type="button"
                        onClick={() => removePlatform(platform)}
                        disabled={loading || submitting}
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-neutral-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                        aria-label={`${ui("deleteTheme")} ${platformLabel(platform, ui)}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {availableToAdd.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {availableToAdd.map((platform) => (
                  <button
                    key={platform}
                    type="button"
                    onClick={() => addPlatform(platform)}
                    disabled={loading || submitting}
                    className="inline-flex items-center gap-1 rounded-md border border-dashed border-neutral-300 bg-white px-2 py-1 text-xs text-neutral-600 hover:border-neutral-400 hover:text-black disabled:opacity-50"
                  >
                    <Plus className="h-3 w-3" />
                    {platformLabel(platform, ui)}
                  </button>
                ))}
              </div>
            ) : null}
          </section>

          <section>
            <p className="mb-2 text-xs font-medium text-neutral-500">{ui("syncSinceLabel")}</p>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={syncSince}
                onChange={(event) => setSyncSince(event.target.value)}
                disabled={loading || submitting}
                className="w-[10.5rem] rounded-md border border-neutral-200 bg-white px-2.5 py-2 text-sm shadow-sm outline-none focus:border-neutral-400 disabled:opacity-50"
              />
              {syncSince ? (
                <button
                  type="button"
                  onClick={() => setSyncSince("")}
                  disabled={loading || submitting}
                  className="text-xs text-muted underline-offset-2 hover:text-black hover:underline disabled:opacity-50"
                >
                  {ui("syncSinceClear")}
                </button>
              ) : null}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{ui("syncSinceHint")}</p>
          </section>

          <section className="rounded-lg border border-neutral-100 bg-neutral-50/50 px-3 py-2.5">
            <label className="flex cursor-pointer items-center gap-2.5">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-neutral-300"
                checked={useAiSummary}
                onChange={(event) => setUseAiSummary(event.target.checked)}
                disabled={loading || submitting}
              />
              <span className="text-sm text-neutral-800">{ui("syncUseAiSummary")}</span>
            </label>
          </section>
        </div>

        <div className="border-t border-neutral-100 px-4 py-3">
          <button
            type="button"
            onClick={() => void handleSync()}
            disabled={loading || submitting || activePlatforms.length === 0}
            className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white shadow-sm hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {submitting ? ui("syncing") : ui("syncSelectedNow")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SubscriptionSettingsButton(props: {
  locale: Locale;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [open, setOpen] = useState(false);
  const syncPollStarted = useRef(false);

  function handleSyncStarted(): void {
    if (syncPollStarted.current || !props.onMessage) {
      return;
    }
    syncPollStarted.current = true;
    pollSyncUntilDone(props.onMessage, ui);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={ui("subscriptionSettings")}
        aria-label={ui("subscriptionSettings")}
        className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-3 py-1.5 text-sm hover:bg-soft"
      >
        <Settings2 className="h-4 w-4" />
      </button>
      <SubscriptionSettingsPanel
        locale={props.locale}
        open={open}
        onClose={() => setOpen(false)}
        onMessage={props.onMessage}
        onSyncStarted={handleSyncStarted}
      />
    </>
  );
}

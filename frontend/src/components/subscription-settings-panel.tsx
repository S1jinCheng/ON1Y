"use client";

import { Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getDistillBackfillStatus,
  getSubscriptionSettings,
  getSubscriptionSyncStatus,
  runDistillBackfill,
  runHotlistSync,
  runSubscriptionSync,
  saveSubscriptionSettings
} from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";

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
        const enqueued = status.last_report?.bilibili?.poll?.enqueued ?? 0;
        const deferred = status.last_report?.bilibili?.poll?.ups_deferred ?? 0;
        const rateLimited = status.last_report?.bilibili?.poll?.rate_limited ?? 0;
        const distilled = status.last_report?.enrich?.distill?.distilled ?? 0;
        let message = `${ui("syncDone")}: +${enqueued}`;
        if (distilled > 0) {
          message += ` · ${ui("bilibiliDistillDone")} ${distilled}`;
        }
        if (deferred > 0) {
          message += ` · ${ui("syncDeferred")} ${deferred}`;
        }
        if (rateLimited > 0) {
          message += ` · ${ui("syncRateLimited")} ${rateLimited}`;
        }
        onMessage(message);
      } catch (error) {
        window.clearInterval(timer);
        onMessage(error instanceof Error ? error.message : String(error));
      }
    })();
  }, 3000);
}

function pollDistillUntilDone(onMessage: (message: string) => void, ui: (key: UiKey) => string): void {
  const timer = window.setInterval(() => {
    void (async () => {
      try {
        const status = await getDistillBackfillStatus();
        if (status.running) {
          return;
        }
        window.clearInterval(timer);
        if (status.error) {
          onMessage(status.error);
          return;
        }
        const distilled = status.distilled ?? 0;
        const failed = status.failed ?? 0;
        let message = `${ui("bilibiliDistillDone")}: ${distilled}`;
        if (failed > 0) {
          message += ` · ${ui("bilibiliDistillFailed")} ${failed}`;
        }
        onMessage(message);
      } catch (error) {
        window.clearInterval(timer);
        onMessage(error instanceof Error ? error.message : String(error));
      }
    })();
  }, 5000);
}

export function SubscriptionSettingsPanel(props: {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  onMessage?: (message: string) => void;
  onSyncStarted?: () => void;
  onDistillStarted?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [loading, setLoading] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [bilibiliSince, setBilibiliSince] = useState("");

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
        setBilibiliSince(settings.bilibili_sync_since ?? "");
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

  async function handleSave(): Promise<void> {
    setSubmitting(true);
    try {
      await saveSubscriptionSettings({
        bilibili_sync_since: bilibiliSince.trim() || null
      });
      props.onMessage?.(ui("settingsSaved"));
    } catch (error) {
      props.onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSync(): Promise<void> {
    setSubmitting(true);
    try {
      await saveSubscriptionSettings({
        bilibili_sync_since: bilibiliSince.trim() || null
      });
      const result = await runSubscriptionSync({
        platform: "bilibili",
        backfill: Boolean(bilibiliSince.trim()),
        ingest: true,
        ingest_limit: 20,
        subtitle_limit: 10,
        distill_limit: 10
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

  async function handleHotlistSync(): Promise<void> {
    setSubmitting(true);
    try {
      const report = await runHotlistSync({ sources: ["zhihu"] });
      const zh = report.results?.zhihu;
      const created = zh?.created ?? 0;
      const updated = zh?.updated ?? 0;
      props.onMessage?.(`${ui("hotlistSyncDone")}: +${created} / ↻${updated}`);
      props.onClose();
    } catch (error) {
      props.onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBilibiliDistill(): Promise<void> {
    setSubmitting(true);
    try {
      const result = await runDistillBackfill({ platform: "bilibili", max_items: 500 });
      if (!result.started) {
        props.onMessage?.(result.message ?? ui("bilibiliDistillAlreadyRunning"));
        return;
      }
      props.onMessage?.(result.message ?? ui("bilibiliDistillStarted"));
      props.onDistillStarted?.();
      props.onClose();
    } catch (error) {
      props.onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-16">
      <div
        role="dialog"
        aria-labelledby="subscription-settings-title"
        className="w-full max-w-md rounded-lg border border-border bg-white p-4 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id="subscription-settings-title" className="text-base font-semibold">
            {ui("subscriptionSettings")}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            className="rounded px-2 py-1 text-sm text-muted hover:bg-soft hover:text-black"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">{ui("platformBilibili")}</span>
            <span className="block text-xs text-muted">{ui("syncSince")}</span>
            <input
              type="date"
              value={bilibiliSince}
              onChange={(event) => setBilibiliSince(event.target.value)}
              className="w-full rounded-md border border-border px-3 py-2 text-sm"
              disabled={loading || submitting}
            />
            <span className="block text-xs text-muted">{ui("syncSinceHint")}</span>
            <span className="block text-xs text-muted">{ui("bilibiliSyncHint")}</span>
          </label>

          <div className="rounded-md border border-border bg-soft/40 p-3">
            <div className="mb-2 text-sm font-medium">{ui("bilibiliSummaries")}</div>
            <p className="mb-3 text-xs text-muted">{ui("bilibiliSummariesHint")}</p>
            <button
              type="button"
              onClick={() => void handleBilibiliDistill()}
              disabled={loading || submitting}
              className="rounded-md border border-border bg-white px-3 py-1.5 text-sm hover:bg-soft disabled:opacity-50"
            >
              {submitting ? ui("bilibiliDistillRunning") : ui("bilibiliDistillNow")}
            </button>
          </div>

          <div className="rounded-md border border-border bg-soft/40 p-3">
            <div className="mb-2 text-sm font-medium">{ui("hotlistColumn")}</div>
            <p className="mb-3 text-xs text-muted">{ui("hotlistColumnHint")}</p>
            <button
              type="button"
              onClick={() => void handleHotlistSync()}
              disabled={loading || submitting}
              className="rounded-md border border-border bg-white px-3 py-1.5 text-sm hover:bg-soft disabled:opacity-50"
            >
              {submitting ? ui("syncing") : ui("hotlistSyncNow")}
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={loading || submitting}
            className="rounded-md border border-border bg-white px-3 py-1.5 text-sm hover:bg-soft disabled:opacity-50"
          >
            {ui("saveSettings")}
          </button>
          <button
            type="button"
            onClick={() => void handleSync()}
            disabled={loading || submitting}
            className="rounded-md border border-black bg-black px-3 py-1.5 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {submitting ? ui("syncing") : ui("syncNow")}
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
  const [open, setOpen] = useState<boolean>(false);
  const syncPollStarted = useRef<boolean>(false);
  const distillPollStarted = useRef<boolean>(false);

  function handleSyncStarted(): void {
    if (syncPollStarted.current || !props.onMessage) {
      return;
    }
    syncPollStarted.current = true;
    pollSyncUntilDone(props.onMessage, ui);
  }

  function handleDistillStarted(): void {
    if (distillPollStarted.current || !props.onMessage) {
      return;
    }
    distillPollStarted.current = true;
    pollDistillUntilDone(props.onMessage, ui);
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
        onDistillStarted={handleDistillStarted}
      />
    </>
  );
}

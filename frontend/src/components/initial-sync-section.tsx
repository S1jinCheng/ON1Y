"use client";

import { Loader2, RefreshCw } from "lucide-react";

import type { CookieStatus } from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";
import { requestInitialSync } from "@/lib/open-settings";
import { hasSyncCookies } from "@/lib/sync-cookies";

export function InitialSyncSection(props: {
  locale: Locale;
  statuses: CookieStatus[];
  busy?: boolean;
  onClose?: () => void;
}): JSX.Element {
  const ui = (key: UiKey): string => t(props.locale, key);
  const ready = hasSyncCookies(props.statuses);

  return (
    <section className="rounded-xl border border-sky-100 bg-gradient-to-br from-sky-50/80 to-white px-4 py-3.5">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700">
          <RefreshCw className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-neutral-900">{ui("coldStartTitle")}</h3>
          <p className="mt-1 text-xs leading-relaxed text-neutral-600">{ui("initialSyncCookiesDesc")}</p>
          {!ready ? (
            <p className="mt-2 text-xs text-amber-700">{ui("initialSyncNeedCookie")}</p>
          ) : (
            <p className="mt-2 text-xs text-emerald-700">{ui("initialSyncCookieReady")}</p>
          )}
          <button
            type="button"
            disabled={!ready || props.busy}
            onClick={() => {
              props.onClose?.();
              requestInitialSync();
            }}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-black px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {props.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {ui("coldStartStart")}
          </button>
        </div>
      </div>
    </section>
  );
}

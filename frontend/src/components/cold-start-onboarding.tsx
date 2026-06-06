"use client";

import { Snowflake, X } from "lucide-react";
import { useState } from "react";

import { patchUserProfile } from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";

export function ColdStartOnboarding(props: {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  onStart?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [busy, setBusy] = useState(false);

  if (!props.open) {
    return null;
  }

  async function dismiss(): Promise<void> {
    setBusy(true);
    try {
      await patchUserProfile({ cold_start_onboarding_dismissed: true });
    } catch {
      /* still close */
    } finally {
      setBusy(false);
      props.onClose();
    }
  }

  async function start(): Promise<void> {
    setBusy(true);
    try {
      await patchUserProfile({ cold_start_onboarding_dismissed: true });
    } catch {
      /* continue */
    }
    props.onClose();
    if (props.onStart) {
      props.onStart();
      return;
    }
    try {
      sessionStorage.setItem("on1y-auto-cold-start", "1");
    } catch {
      /* ignore */
    }
    window.location.href = "/";
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 p-4">
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-2xl">
        <button
          type="button"
          aria-label="Close"
          disabled={busy}
          onClick={() => void dismiss()}
          className="absolute right-3 top-3 rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="bg-gradient-to-br from-sky-50 to-white px-6 pb-2 pt-8">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-100 text-sky-700">
            <Snowflake className="h-6 w-6" />
          </div>
          <h2 className="mt-4 text-xl font-semibold tracking-tight text-neutral-900">
            {ui("coldStartOnboardingTitle")}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-neutral-600">
            {ui("coldStartOnboardingBody")}
          </p>
        </div>
        <div className="space-y-2 px-6 py-5">
          <ul className="space-y-2 text-sm text-neutral-700">
            <li className="flex gap-2">
              <span className="text-sky-600">1.</span>
              <span>{ui("coldStartOnboardingStep1")}</span>
            </li>
            <li className="flex gap-2">
              <span className="text-sky-600">2.</span>
              <span>{ui("coldStartOnboardingStep2")}</span>
            </li>
            <li className="flex gap-2">
              <span className="text-sky-600">3.</span>
              <span>{ui("coldStartOnboardingStep3")}</span>
            </li>
          </ul>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              disabled={busy}
              onClick={() => void start()}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-black px-4 py-2.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              <Snowflake className="h-4 w-4" />
              {ui("coldStartStart")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void dismiss()}
              className="inline-flex flex-1 items-center justify-center rounded-lg border border-neutral-200 px-4 py-2.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {ui("coldStartOnboardingLater")}
            </button>
          </div>
          <p className="text-center text-[11px] text-neutral-400">{ui("coldStartOnboardingHint")}</p>
        </div>
      </div>
    </div>
  );
}

"use client";

import {
  BarChart3,
  BookOpen,
  Bot,
  ChevronLeft,
  ChevronRight,
  Cookie,
  Flame,
  LayoutDashboard,
  RefreshCw,
  Rss,
  Search,
  Sparkles,
  Upload,
  Users,
  X
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getCookieStatuses, patchUserProfile } from "@/lib/api";
import { t, type Locale, type UiKey } from "@/lib/i18n";
import { openSettingsTab } from "@/lib/open-settings";
import { hasSyncCookies } from "@/lib/sync-cookies";

type GuideStepId = "welcome" | "workbench" | "subscribe" | "setup" | "ai" | "extras" | "start";

type GuideStep = {
  id: GuideStepId;
  icon: typeof Sparkles;
  titleKey: UiKey;
  bodyKey: UiKey;
  bulletKeys: UiKey[];
};

const GUIDE_STEPS: GuideStep[] = [
  {
    id: "welcome",
    icon: Sparkles,
    titleKey: "guideStepWelcomeTitle",
    bodyKey: "guideStepWelcomeBody",
    bulletKeys: ["guideStepWelcomeB1", "guideStepWelcomeB2", "guideStepWelcomeB3", "guideStepWelcomeB4"]
  },
  {
    id: "workbench",
    icon: LayoutDashboard,
    titleKey: "guideStepWorkbenchTitle",
    bodyKey: "guideStepWorkbenchBody",
    bulletKeys: [
      "guideStepWorkbenchB1",
      "guideStepWorkbenchB2",
      "guideStepWorkbenchB3",
      "guideStepWorkbenchB4"
    ]
  },
  {
    id: "subscribe",
    icon: Rss,
    titleKey: "guideStepSubscribeTitle",
    bodyKey: "guideStepSubscribeBody",
    bulletKeys: [
      "guideStepSubscribeB1",
      "guideStepSubscribeB2",
      "guideStepSubscribeB3",
      "guideStepSubscribeB4"
    ]
  },
  {
    id: "setup",
    icon: Cookie,
    titleKey: "guideStepSetupTitle",
    bodyKey: "guideStepSetupBody",
    bulletKeys: ["guideStepSetupB1", "guideStepSetupB2", "guideStepSetupB3", "guideStepSetupB4"]
  },
  {
    id: "ai",
    icon: Bot,
    titleKey: "guideStepAiTitle",
    bodyKey: "guideStepAiBody",
    bulletKeys: ["guideStepAiB1", "guideStepAiB2", "guideStepAiB3", "guideStepAiB4"]
  },
  {
    id: "extras",
    icon: Flame,
    titleKey: "guideStepExtrasTitle",
    bodyKey: "guideStepExtrasBody",
    bulletKeys: ["guideStepExtrasB1", "guideStepExtrasB2", "guideStepExtrasB3", "guideStepExtrasB4"]
  },
  {
    id: "start",
    icon: RefreshCw,
    titleKey: "guideStepStartTitle",
    bodyKey: "guideStepStartBody",
    bulletKeys: ["guideStepStartB1", "guideStepStartB2", "guideStepStartB3"]
  }
];

function StepIcon(props: { step: GuideStep }): JSX.Element {
  const Icon = props.step.icon;
  const accent =
    props.step.id === "setup"
      ? "bg-amber-100 text-amber-700"
      : props.step.id === "start"
        ? "bg-emerald-100 text-emerald-700"
        : "bg-sky-100 text-sky-700";
  return (
    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${accent}`}>
      <Icon className="h-5 w-5" />
    </div>
  );
}

function FeaturePill(props: { icon: JSX.Element; label: string }): JSX.Element {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 text-[11px] text-neutral-600">
      {props.icon}
      {props.label}
    </span>
  );
}

export function FirstRunGuide(props: {
  locale: Locale;
  open: boolean;
  onClose: () => void;
  onStartSync?: () => void;
}): JSX.Element | null {
  const ui = (key: UiKey): string => t(props.locale, key);
  const [busy, setBusy] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [cookieReady, setCookieReady] = useState(false);

  const step = GUIDE_STEPS[stepIndex];
  const isLast = stepIndex === GUIDE_STEPS.length - 1;
  const progress = ((stepIndex + 1) / GUIDE_STEPS.length) * 100;

  const platformLabels =
    props.locale === "zh" ? "哔哩哔哩 / YouTube / 知乎" : "Bilibili / YouTube / Zhihu";

  useEffect(() => {
    if (!props.open) {
      setStepIndex(0);
      return;
    }
    let cancelled = false;
    void getCookieStatuses()
      .then((result) => {
        if (!cancelled) {
          setCookieReady(hasSyncCookies(result.platforms));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCookieReady(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [props.open, stepIndex]);

  const featurePills = useMemo(() => {
    if (step.id === "workbench") {
      return [
        { icon: <Search className="h-3 w-3" />, label: ui("guidePillSearch") },
        { icon: <BookOpen className="h-3 w-3" />, label: ui("guidePillReader") },
        { icon: <LayoutDashboard className="h-3 w-3" />, label: ui("guidePillThemes") }
      ];
    }
    if (step.id === "extras") {
      return [
        { icon: <BarChart3 className="h-3 w-3" />, label: ui("stats") },
        { icon: <Flame className="h-3 w-3" />, label: ui("collectionHotlist") },
        { icon: <Upload className="h-3 w-3" />, label: ui("upload") },
        { icon: <Users className="h-3 w-3" />, label: ui("guidePillAccounts") }
      ];
    }
    return [];
  }, [step.id, ui]);

  if (!props.open || !step) {
    return null;
  }

  async function finishGuide(): Promise<void> {
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

  async function finishAndStartSync(): Promise<void> {
    setBusy(true);
    try {
      await patchUserProfile({ cold_start_onboarding_dismissed: true });
    } catch {
      /* continue */
    } finally {
      setBusy(false);
    }
    props.onClose();
    props.onStartSync?.();
  }

  function openCookiesSettings(): void {
    void finishGuide();
    openSettingsTab("subscriptions");
  }

  function openAiSettings(): void {
    void finishGuide();
    openSettingsTab("ai");
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]">
      <div className="relative flex max-h-[min(90vh,720px)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-2xl">
        <div className="h-1 bg-neutral-100">
          <div
            className="h-full bg-sky-500 transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>

        <button
          type="button"
          aria-label={ui("guideSkip")}
          disabled={busy}
          onClick={() => void finishGuide()}
          className="absolute right-3 top-4 z-10 rounded-md p-1.5 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4 pt-6 sm:px-8">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
            {ui("guideStepOf")
              .replace("{current}", String(stepIndex + 1))
              .replace("{total}", String(GUIDE_STEPS.length))}
          </div>

          <div className="flex items-start gap-4">
            <StepIcon step={step} />
            <div className="min-w-0 flex-1 pr-6">
              <h2 className="text-xl font-semibold tracking-tight text-neutral-900">{ui(step.titleKey)}</h2>
              <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                {ui(step.bodyKey).replace("{platforms}", platformLabels)}
              </p>
            </div>
          </div>

          <ul className="mt-5 space-y-2.5">
            {step.bulletKeys.map((key, index) => (
              <li key={key} className="flex gap-3 text-sm leading-relaxed text-neutral-700">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-[11px] font-semibold text-neutral-500">
                  {index + 1}
                </span>
                <span>{ui(key).replace("{platforms}", platformLabels)}</span>
              </li>
            ))}
          </ul>

          {featurePills.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-2">{featurePills.map((pill) => (
                <FeaturePill key={pill.label} icon={pill.icon} label={pill.label} />
              ))}</div>
          ) : null}

          {step.id === "setup" ? (
            <div
              className={`mt-5 rounded-xl px-3 py-2.5 text-xs ${
                cookieReady ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"
              }`}
            >
              {cookieReady ? ui("initialSyncCookieReady") : ui("initialSyncNeedCookie")}
            </div>
          ) : null}

          {step.id === "start" ? (
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                disabled={busy}
                onClick={openCookiesSettings}
                className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-3 text-left text-sm hover:bg-neutral-100 disabled:opacity-60"
              >
                <Cookie className="h-5 w-5 shrink-0 text-amber-600" />
                <span>
                  <span className="block font-medium text-neutral-900">{ui("guideCtaCookies")}</span>
                  <span className="mt-0.5 block text-xs text-neutral-500">{ui("guideCtaCookiesHint")}</span>
                </span>
              </button>
              <button
                type="button"
                disabled={busy || !cookieReady}
                onClick={() => void finishAndStartSync()}
                className="flex items-center gap-3 rounded-xl border border-sky-200 bg-sky-50 px-3 py-3 text-left text-sm hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className="h-5 w-5 shrink-0 text-sky-700" />
                <span>
                  <span className="block font-medium text-neutral-900">{ui("coldStartStart")}</span>
                  <span className="mt-0.5 block text-xs text-neutral-500">{ui("guideCtaSyncHint")}</span>
                </span>
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={openAiSettings}
                className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white px-3 py-3 text-left text-sm hover:bg-neutral-50 disabled:opacity-60 sm:col-span-2"
              >
                <Bot className="h-5 w-5 shrink-0 text-violet-600" />
                <span>
                  <span className="block font-medium text-neutral-900">{ui("guideCtaAi")}</span>
                  <span className="mt-0.5 block text-xs text-neutral-500">{ui("guideCtaAiHint")}</span>
                </span>
              </button>
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-neutral-100 bg-neutral-50/80 px-6 py-4 sm:px-8">
          <button
            type="button"
            disabled={busy || stepIndex === 0}
            onClick={() => setStepIndex((value) => Math.max(0, value - 1))}
            className="inline-flex items-center gap-1 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-50 disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
            {ui("guideBack")}
          </button>

          <div className="hidden items-center gap-1.5 sm:flex">
            {GUIDE_STEPS.map((item, index) => (
              <button
                key={item.id}
                type="button"
                aria-label={ui(item.titleKey)}
                onClick={() => setStepIndex(index)}
                className={`h-2 rounded-full transition-all ${
                  index === stepIndex ? "w-6 bg-sky-500" : "w-2 bg-neutral-300 hover:bg-neutral-400"
                }`}
              />
            ))}
          </div>

          {isLast ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void finishGuide()}
              className="inline-flex items-center gap-1 rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {ui("guideExplore")}
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => setStepIndex((value) => Math.min(GUIDE_STEPS.length - 1, value + 1))}
              className="inline-flex items-center gap-1 rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {ui("guideNext")}
              <ChevronRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** @deprecated use FirstRunGuide */
export const ColdStartOnboarding = FirstRunGuide;

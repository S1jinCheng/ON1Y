"use client";

import {
  Bot,
  ClipboardPaste,
  Cookie,
  KeyRound,
  Loader2,
  Send,
  SlidersHorizontal,
  Trash2,
  Upload,
  UserCircle2,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  deleteCookieFile,
  getCookieStatuses,
  getDesktopAppStatus,
  getLlmSettings,
  getSubscriptionSettings,
  getUserProfile,
  importCookieFromClipboard,
  patchUserProfile,
  saveLlmSettings,
  saveSubscriptionSettings,
  setAutostart,
  testLlmSettings,
  updateAuthProfile,
  uploadCookieFile,
  type AuthUser,
  type CookiePlatform,
  type CookieStatus,
  type DesktopAppStatus,
  type LlmSettingsView,
  type UserProfile
} from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { persistStoredLocale } from "@/lib/locale-preference";

type TabKey = "general" | "account" | "platforms" | "cookies" | "ai" | "push";

type Props = {
  open: boolean;
  onClose: () => void;
  locale: Locale;
  user: AuthUser | null;
  onUserUpdated?: (user: AuthUser) => void;
  onLocaleChange?: (locale: Locale) => void;
  onMessage?: (message: string) => void;
};

const COOKIE_PLATFORMS: { key: CookiePlatform; label: string }[] = [
  { key: "youtube", label: "YouTube" },
  { key: "bilibili", label: "哔哩哔哩" },
  { key: "zhihu", label: "知乎" },
  { key: "xiaohongshu", label: "小红书" },
  { key: "twitter", label: "X / Twitter" }
];

const SUB_PLATFORMS: { key: "bilibili" | "youtube" | "zhihu"; label: string }[] = [
  { key: "bilibili", label: "哔哩哔哩" },
  { key: "youtube", label: "YouTube" },
  { key: "zhihu", label: "知乎" }
];

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

export function SettingsCenter(props: Props): JSX.Element | null {
  const { open, onClose, locale, user } = props;
  const [tab, setTab] = useState<TabKey>("general");

  if (!open) {
    return null;
  }

  const tabs: { key: TabKey; label: string; icon: JSX.Element }[] = [
    { key: "general", label: L(locale, "通用", "General"), icon: <SlidersHorizontal className="h-4 w-4" /> },
    { key: "account", label: L(locale, "个人资料", "Profile"), icon: <UserCircle2 className="h-4 w-4" /> },
    { key: "platforms", label: L(locale, "订阅", "Subscriptions"), icon: <Send className="h-4 w-4" /> },
    { key: "cookies", label: L(locale, "Cookie", "Cookies"), icon: <Cookie className="h-4 w-4" /> },
    { key: "ai", label: L(locale, "AI", "AI"), icon: <Bot className="h-4 w-4" /> },
    { key: "push", label: L(locale, "推送", "Delivery"), icon: <KeyRound className="h-4 w-4" /> }
  ];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
      <div className="flex h-[600px] max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-2xl">
        <aside className="flex w-48 shrink-0 flex-col border-r border-neutral-100 bg-neutral-50/70 p-3">
          <div className="px-2 py-2 text-sm font-semibold tracking-tight text-neutral-900">
            {L(locale, "设置", "Settings")}
          </div>
          <nav className="mt-1 space-y-0.5">
            {tabs.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setTab(item.key)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition ${
                  tab === item.key
                    ? "bg-white font-medium text-neutral-900 shadow-sm"
                    : "text-neutral-500 hover:bg-white/70 hover:text-neutral-900"
                }`}
              >
                {item.icon}
                <span className="truncate">{item.label}</span>
              </button>
            ))}
          </nav>
          <div className="mt-auto px-2 py-2 text-[11px] text-neutral-400">
            {user ? `@${user.username}` : ""}
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
            <h2 className="text-sm font-semibold tracking-tight text-neutral-900">
              {tabs.find((t) => t.key === tab)?.label}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-md text-neutral-400 transition hover:bg-neutral-100 hover:text-black"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 scrollbar-thin">
            {tab === "general" ? (
              <GeneralTab
                locale={locale}
                onLocaleChange={props.onLocaleChange}
                onMessage={props.onMessage}
              />
            ) : null}
            {tab === "account" ? (
              <AccountTab locale={locale} user={user} onUserUpdated={props.onUserUpdated} onMessage={props.onMessage} />
            ) : null}
            {tab === "platforms" ? <PlatformsTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "cookies" ? <CookiesTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "ai" ? <AiTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "push" ? <PushTab locale={locale} onMessage={props.onMessage} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldLabel(props: { children: React.ReactNode }): JSX.Element {
  return <span className="mb-1.5 block text-xs font-medium text-neutral-600">{props.children}</span>;
}

function ToggleRow(props: {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}): JSX.Element {
  return (
    <label className="flex items-start justify-between gap-4 rounded-lg border border-neutral-100 bg-neutral-50/60 px-3 py-3">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-neutral-900">{props.label}</span>
        {props.description ? (
          <span className="mt-1 block text-xs leading-relaxed text-neutral-500">{props.description}</span>
        ) : null}
      </span>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 accent-black"
        checked={props.checked}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)}
      />
    </label>
  );
}

function GeneralTab(props: {
  locale: Locale;
  onLocaleChange?: (locale: Locale) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [language, setLanguage] = useState<Locale>(locale);
  const [openBrowser, setOpenBrowser] = useState(true);
  const [autostart, setAutostartEnabled] = useState(false);
  const [autostartSupported, setAutostartSupported] = useState(false);
  const [desktop, setDesktop] = useState<DesktopAppStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [profile, status] = await Promise.all([getUserProfile(), getDesktopAppStatus()]);
        if (cancelled) {
          return;
        }
        const appLocale = profile.app?.locale === "en" ? "en" : "zh";
        setLanguage(appLocale);
        setOpenBrowser(profile.app?.open_browser_on_start ?? true);
        setAutostartEnabled(status.autostart_enabled);
        setAutostartSupported(status.autostart_supported);
        setDesktop(status);
      } catch (err) {
        props.onMessage?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props]);

  async function saveGeneral(): Promise<void> {
    setSaving(true);
    try {
      await patchUserProfile({
        locale: language,
        open_browser_on_start: openBrowser
      });
      persistStoredLocale(language);
      props.onLocaleChange?.(language);
      props.onMessage?.(L(locale, "通用设置已保存", "General settings saved"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onAutostartToggle(enabled: boolean): Promise<void> {
    try {
      const result = await setAutostart(enabled);
      setAutostartEnabled(result.autostart_enabled);
      props.onMessage?.(
        enabled
          ? L(locale, "已开启登录时自动启动", "Autostart on login enabled")
          : L(locale, "已关闭登录时自动启动", "Autostart on login disabled")
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "语言与地区", "Language")}
        </h3>
        <div className="inline-flex overflow-hidden rounded-lg border border-neutral-200 text-sm">
          <button
            type="button"
            onClick={() => setLanguage("zh")}
            className={`px-4 py-2 ${language === "zh" ? "bg-black text-white" : "bg-white text-neutral-700"}`}
          >
            中文
          </button>
          <button
            type="button"
            onClick={() => setLanguage("en")}
            className={`px-4 py-2 ${language === "en" ? "bg-black text-white" : "bg-white text-neutral-700"}`}
          >
            English
          </button>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "启动", "Startup")}
        </h3>
        <ToggleRow
          label={L(locale, "登录 Windows 时自动启动 On1y", "Start On1y when I sign in to Windows")}
          description={L(
            locale,
            "登录时在后台启动后端与前端（窗口最小化）。",
            "Starts backend and frontend in the background on sign-in (minimized windows)."
          )}
          checked={autostart}
          disabled={!autostartSupported}
          onChange={(v) => void onAutostartToggle(v)}
        />
        <ToggleRow
          label={L(locale, "启动时打开浏览器", "Open browser on start")}
          description={L(
            locale,
            "登录自启或双击桌面图标时自动打开工作台；关闭后需手动访问 http://127.0.0.1:3000",
            "Opens the workspace on sign-in autostart or desktop launch; if off, visit http://127.0.0.1:3000 manually."
          )}
          checked={openBrowser}
          onChange={setOpenBrowser}
        />
        <div className="flex justify-end">
          <button type="button" className={primaryBtn} disabled={saving} onClick={() => void saveGeneral()}>
            {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
          </button>
        </div>
      </section>

      <section className="space-y-2 rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-3 text-xs leading-relaxed text-amber-900/80">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-800/70">
          {L(locale, "后台同步", "Background sync")}
        </h3>
        <p>
          {L(
            locale,
            "启动后默认先等几分钟再同步；首轮只拉订阅、不入库。大批量入库请在空闲时用右上角「订阅」手动同步，或调小 .env 里的 AUTO_SYNC_*_LIMIT。",
            "After startup, sync waits a few minutes; the first tick only polls feeds. For heavy catch-up, use Subscriptions in the header or lower AUTO_SYNC_*_LIMIT in .env."
          )}
        </p>
      </section>

      <section className="space-y-2 rounded-lg border border-neutral-100 bg-neutral-50/50 px-3 py-3 text-xs text-neutral-500">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "关于", "About")}
        </h3>
        <p>
          {L(locale, "版本", "Version")}: {desktop?.version ?? "—"}
        </p>
        <p className="break-all">
          {L(locale, "数据目录", "Data")}: {desktop?.data_dir ?? "—"}
        </p>
        <p>
          {L(locale, "工作台", "App")}: http://127.0.0.1:3000
        </p>
      </section>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-900 disabled:opacity-50";
const primaryBtn =
  "rounded-lg bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50";
const ghostBtn =
  "rounded-lg border border-neutral-200 bg-white px-4 py-2 text-sm text-neutral-700 transition hover:bg-neutral-50 disabled:opacity-50";

function AccountTab(props: {
  locale: Locale;
  user: AuthUser | null;
  onUserUpdated?: (user: AuthUser) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [displayName, setDisplayName] = useState(props.user?.display_name ?? "");
  const [email, setEmail] = useState(props.user?.email ?? "");
  const [savingProfile, setSavingProfile] = useState(false);

  async function saveProfile(): Promise<void> {
    setSavingProfile(true);
    try {
      const result = await updateAuthProfile({ display_name: displayName.trim(), email: email.trim() || null });
      props.onUserUpdated?.(result.user);
      props.onMessage?.(L(locale, "账户已更新", "Account updated"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingProfile(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "基本信息", "Basic info")}
        </h3>
        <div>
          <FieldLabel>{L(locale, "显示名称", "Display name")}</FieldLabel>
          <input className={inputClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <FieldLabel>{L(locale, "邮箱", "Email")}</FieldLabel>
          <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div className="flex justify-end">
          <button type="button" className={primaryBtn} disabled={savingProfile} onClick={() => void saveProfile()}>
            {savingProfile ? L(locale, "保存中…", "Saving…") : L(locale, "保存资料", "Save profile")}
          </button>
        </div>
      </section>
    </div>
  );
}

function PlatformsTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  const [enabled, setEnabled] = useState<string[]>(["bilibili", "youtube", "zhihu"]);
  const [syncSince, setSyncSince] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const settings = await getSubscriptionSettings();
        if (cancelled) {
          return;
        }
        setEnabled(settings.enabled_platforms ?? ["bilibili", "youtube", "zhihu"]);
        setSyncSince(settings.bilibili_sync_since ?? settings.youtube_sync_since ?? settings.zhihu_sync_since ?? "");
      } catch (err) {
        props.onMessage?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props]);

  function toggle(key: string): void {
    setEnabled((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));
  }

  async function save(): Promise<void> {
    if (enabled.length === 0) {
      props.onMessage?.(L(locale, "至少选择一个平台", "Select at least one platform"));
      return;
    }
    setSaving(true);
    try {
      const since = syncSince.trim();
      await saveSubscriptionSettings({
        enabled_platforms: enabled,
        bilibili_sync_since: enabled.includes("bilibili") ? since : undefined,
        youtube_sync_since: enabled.includes("youtube") ? since : undefined,
        zhihu_sync_since: enabled.includes("zhihu") ? since : undefined
      });
      props.onMessage?.(L(locale, "订阅设置已保存", "Subscription settings saved"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-neutral-500">
        {L(
          locale,
          "选择你想订阅的平台。具体的关注列表通过 Cookie 登录态自动同步；右上角「同步」按钮可立即拉取。",
          "Choose platforms to subscribe. Follow lists sync via your login cookies; use the Sync button to pull now."
        )}
      </p>
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{L(locale, "启用平台", "Enabled platforms")}</h3>
        <div className="space-y-2">
          {SUB_PLATFORMS.map((platform) => (
            <label
              key={platform.key}
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 hover:bg-neutral-50"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-neutral-300"
                checked={enabled.includes(platform.key)}
                onChange={() => toggle(platform.key)}
              />
              <span className="text-sm text-neutral-800">{platform.label}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{L(locale, "起始日期", "Sync since")}</h3>
        <div className="flex items-center gap-2">
          <input type="date" className={`${inputClass} w-44`} value={syncSince} onChange={(e) => setSyncSince(e.target.value)} />
          {syncSince ? (
            <button type="button" className="text-xs text-neutral-400 hover:text-black" onClick={() => setSyncSince("")}>
              {L(locale, "清除", "Clear")}
            </button>
          ) : null}
        </div>
        <p className="text-[11px] text-neutral-400">
          {L(locale, "只同步该日期之后发布的内容；留空则不限制。", "Only ingest content published after this date; empty = no limit.")}
        </p>
      </section>

      <div className="flex justify-end">
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
      </div>
    </div>
  );
}

function CookiesTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  const [statuses, setStatuses] = useState<CookieStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<CookiePlatform | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  async function reload(): Promise<void> {
    try {
      const result = await getCookieStatuses();
      setStatuses(result.platforms);
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function statusFor(key: CookiePlatform): CookieStatus | undefined {
    return statuses.find((s) => s.platform === key);
  }

  async function onPick(platform: CookiePlatform, file: File | null): Promise<void> {
    if (!file) {
      return;
    }
    setBusy(platform);
    try {
      const result = await uploadCookieFile(platform, file);
      props.onMessage?.(L(locale, `已导入 ${result.count} 条 Cookie`, `Imported ${result.count} cookies`));
      await reload();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function onPaste(platform: CookiePlatform): Promise<void> {
    setBusy(platform);
    try {
      const result = await importCookieFromClipboard(platform);
      props.onMessage?.(L(locale, `已从剪贴板导入 ${result.count} 条 Cookie`, `Pasted ${result.count} cookies from clipboard`));
      await reload();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(platform: CookiePlatform): Promise<void> {
    setBusy(platform);
    try {
      await deleteCookieFile(platform);
      props.onMessage?.(L(locale, "已删除", "Removed"));
      await reload();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-neutral-500">
        {L(
          locale,
          "用 Cookie-Editor 等扩展导出 JSON，复制到剪贴板后点「粘贴导入」，或选择 JSON 文件上传。Cookie 仅保存在本地。",
          "Export JSON with Cookie-Editor, copy to clipboard and click Paste, or upload a JSON file. Cookies stay on your machine only."
        )}
      </p>
      <div className="space-y-2">
        {COOKIE_PLATFORMS.map((platform) => {
          const status = statusFor(platform.key);
          const exists = status?.exists ?? false;
          return (
            <div
              key={platform.key}
              className="flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2.5"
            >
              <span
                className={`flex h-2 w-2 shrink-0 rounded-full ${exists ? "bg-emerald-500" : "bg-neutral-300"}`}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-neutral-900">{platform.label}</div>
                <div className="text-[11px] text-neutral-400">
                  {exists
                    ? L(locale, `${status?.count ?? 0} 条 · ${status?.updated_at?.replace("T", " ") ?? ""}`, `${status?.count ?? 0} cookies · ${status?.updated_at?.replace("T", " ") ?? ""}`)
                    : L(locale, "未配置", "Not configured")}
                </div>
              </div>
              <input
                ref={(el) => {
                  fileInputs.current[platform.key] = el;
                }}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => void onPick(platform.key, e.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
                disabled={busy === platform.key}
                onClick={() => void onPaste(platform.key)}
                title={L(locale, "从剪贴板粘贴 Cookie JSON", "Paste cookie JSON from clipboard")}
              >
                {busy === platform.key ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ClipboardPaste className="h-3.5 w-3.5" />}
                {L(locale, "粘贴", "Paste")}
              </button>
              <button
                type="button"
                className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
                disabled={busy === platform.key}
                onClick={() => fileInputs.current[platform.key]?.click()}
              >
                <Upload className="h-3.5 w-3.5" />
                {L(locale, "文件", "File")}
              </button>
              {exists ? (
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-neutral-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                  disabled={busy === platform.key}
                  onClick={() => void onDelete(platform.key)}
                  aria-label="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AiTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  const [view, setView] = useState<LlmSettingsView | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getLlmSettings();
        if (cancelled) {
          return;
        }
        setView(data);
        setBaseUrl(data.base_url);
        setModel(data.model);
      } catch (err) {
        props.onMessage?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props]);

  async function save(): Promise<void> {
    setSaving(true);
    try {
      const data = await saveLlmSettings({ base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() || undefined });
      setView(data);
      setApiKey("");
      props.onMessage?.(L(locale, "AI 设置已保存", "AI settings saved"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function test(): Promise<void> {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testLlmSettings(
        apiKey.trim() ? { base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() } : undefined
      );
      setTestResult({
        ok: result.ok,
        text: result.ok ? `${result.model} · ${result.reply_preview ?? "ok"}` : result.error ?? "failed"
      });
    } catch (err) {
      setTestResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setTesting(false);
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-neutral-500">
        {L(
          locale,
          "兼容 OpenAI 接口（DeepSeek、OpenAI、Moonshot 等）。Key 仅保存在你本地服务，按用户隔离，用于自动摘要与分类。",
          "Any OpenAI-compatible provider (DeepSeek, OpenAI, Moonshot…). Your key stays local, isolated per user, used for auto summary & tagging."
        )}
      </p>
      <div>
        <FieldLabel>Base URL</FieldLabel>
        <input className={inputClass} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={view?.defaults.base_url} />
      </div>
      <div>
        <FieldLabel>{L(locale, "模型", "Model")}</FieldLabel>
        <input className={inputClass} value={model} onChange={(e) => setModel(e.target.value)} placeholder={view?.defaults.model} />
      </div>
      <div>
        <FieldLabel>API Key</FieldLabel>
        <input
          className={inputClass}
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={view?.api_key_set ? `${L(locale, "已设置", "set")}: ${view.api_key_preview}` : "sk-..."}
        />
        <p className="mt-1 text-[11px] text-neutral-400">
          {view?.api_key_set
            ? L(locale, "留空表示保留现有 Key。", "Leave empty to keep the existing key.")
            : L(locale, "尚未配置 Key。", "No key configured yet.")}
        </p>
      </div>

      {testResult ? (
        <div
          className={`rounded-lg px-3 py-2 text-xs ${
            testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-600"
          }`}
        >
          {testResult.ok ? L(locale, "连接成功 · ", "Connected · ") : L(locale, "连接失败 · ", "Failed · ")}
          {testResult.text}
        </div>
      ) : null}

      <div className="flex justify-end gap-2">
        <button type="button" className={ghostBtn} disabled={testing} onClick={() => void test()}>
          {testing ? L(locale, "测试中…", "Testing…") : L(locale, "测试连接", "Test")}
        </button>
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
      </div>
    </div>
  );
}

function PushTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [kindleTo, setKindleTo] = useState("");
  const [autoIngest, setAutoIngest] = useState(false);
  const [autoKindle, setAutoKindle] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getUserProfile();
        if (cancelled) {
          return;
        }
        setProfile(data);
        setKindleTo(data.kindle.send_to);
        setAutoIngest(data.economist.auto_ingest_enabled);
        setAutoKindle(data.economist.auto_kindle_enabled);
      } catch (err) {
        props.onMessage?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props]);

  async function save(): Promise<void> {
    setSaving(true);
    try {
      const data = await patchUserProfile({
        kindle_send_to: kindleTo.trim(),
        kindle_enabled: Boolean(kindleTo.trim()),
        economist_auto_ingest: autoIngest,
        economist_auto_kindle: autoKindle
      });
      setProfile(data);
      props.onMessage?.(L(locale, "推送设置已保存", "Delivery settings saved"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  const smtpReady = profile?.integrations.smtp.configured ?? false;

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-neutral-500">
        {L(
          locale,
          "经济学人新刊可自动入库并推送到 Kindle。发件邮箱需在 Amazon「已认可发件人」中，SMTP 在服务端 .env 配置。",
          "New Economist editions can auto-ingest and send to Kindle. The sender must be approved in Amazon; SMTP is set in server .env."
        )}
      </p>

      <div>
        <FieldLabel>{L(locale, "Kindle 接收邮箱", "Kindle email")}</FieldLabel>
        <input className={inputClass} value={kindleTo} onChange={(e) => setKindleTo(e.target.value)} placeholder="xxx@kindle.com" />
      </div>

      <div className="space-y-2">
        <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 hover:bg-neutral-50">
          <input type="checkbox" className="h-4 w-4 rounded border-neutral-300" checked={autoIngest} onChange={(e) => setAutoIngest(e.target.checked)} />
          <span className="text-sm text-neutral-800">{L(locale, "自动入库经济学人新刊", "Auto-ingest new Economist editions")}</span>
        </label>
        <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 hover:bg-neutral-50">
          <input type="checkbox" className="h-4 w-4 rounded border-neutral-300" checked={autoKindle} onChange={(e) => setAutoKindle(e.target.checked)} />
          <span className="text-sm text-neutral-800">{L(locale, "新刊自动推送到 Kindle", "Auto-send new editions to Kindle")}</span>
        </label>
      </div>

      <div
        className={`rounded-lg px-3 py-2 text-xs ${smtpReady ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}
      >
        {smtpReady
          ? L(locale, `SMTP 已配置 · 发件 ${profile?.integrations.smtp.from ?? ""}`, `SMTP ready · from ${profile?.integrations.smtp.from ?? ""}`)
          : L(locale, "SMTP 未配置，无法发送邮件（在 .env 设置 ON1Y_SMTP_*）", "SMTP not configured (set ON1Y_SMTP_* in .env)")}
      </div>

      <div className="flex justify-end">
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
      </div>
    </div>
  );
}

function LoadingRow(props: { locale: Locale }): JSX.Element {
  return (
    <div className="flex items-center gap-2 text-sm text-neutral-400">
      <Loader2 className="h-4 w-4 animate-spin" />
      {L(props.locale, "加载中…", "Loading…")}
    </div>
  );
}

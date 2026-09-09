"use client";

import {
  Bot,
  BookOpen,
  ClipboardPaste,
  Cookie,
  Download,
  FolderOpen,
  FileText,
  Info,
  KeyRound,
  Loader2,
  QrCode,
  RefreshCw,
  MessageCircle,
  SlidersHorizontal,
  Trash2,
  Upload,
  UserCircle2,
  X
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import {
  deleteCookieFile,
  buildUserArchiveExportUrl,
  exportUserArchive,
  fetchAuthStatus,
  fetchAuthUsers,
  getCookieStatuses,
  verifyCookiePlatform,
  getDesktopAppStatus,
  getLlmSettings,
  getNetworkSettings,
  getObsidianSettings,
  getObsidianSyncStatus,
  getSubscriptionSettings,
  getSubscriptionSyncStatus,
  getSmtpSettings,
  getSyncSettings,
  getUserProfile,
  importCookieFromClipboard,
  importUserArchive,
  logout,
  patchDesktopPrefs,
  patchUserProfile,
  runSubscriptionSync,
  runObsidianSync,
  saveLlmSettings,
  saveNetworkSettings,
  saveObsidianSettings,
  saveSmtpSettings,
  saveSubscriptionSettings,
  saveSyncSettings,
  setAutostart,
  testNetworkProxy,
  switchAccount,
  testLlmSettings,
  testSmtpSettings,
  updateAuthProfile,
  fetchBookSettings,
  saveBookSettings,
  fetchBookSources,
  saveBookSources,
  scanBookFolder,
  fetchPaperSettings,
  savePaperSettings,
  scanPaperFolder,
  syncZoteroPapers,
  type AuthUser,
  type CookieAccountInfo,
  type CookiePlatform,
  type CookieStatus,
  type DesktopAppStatus,
  type LlmSettingsView,
  type NetworkSettingsView,
  type ObsidianSettingsView,
  type SmtpSettingsView,
  type SyncSettingsView,
  type UserProfile
} from "@/lib/api";
import { getRecentAuthUsernames } from "@/lib/auth";
import { notifyAppearanceChange } from "@/components/appearance-provider";
import { InitialSyncSection } from "@/components/initial-sync-section";
import { TelegramSettingsPanel } from "@/components/telegram-settings-panel";
import { CookieQrLoginDialog } from "@/components/cookie-qr-login-dialog";
import { type AppearanceMode, persistStoredAppearance } from "@/lib/appearance";
import type { Locale } from "@/lib/i18n";
import {
  consumeRequestedSettingsTab,
  showFirstRunGuide,
  type SettingsTabKey
} from "@/lib/open-settings";
import { persistStoredLocale } from "@/lib/locale-preference";
import { isDesktopShell, pickFolder } from "@/lib/pick-data-folder";
import { pickPdfApplication } from "@/lib/pdf-application";
import type { BookFormat } from "@/lib/book-types";
import type { PaperSettings } from "@/lib/paper-types";
import { buildBuiltinSourcesSave, readBuiltinToggles } from "@/lib/book-builtin";
import { saveArchiveFile, triggerBrowserFileDownload } from "@/lib/save-archive-file";

const BOOK_FORMATS: BookFormat[] = ["epub", "pdf", "mobi"];

type TabKey = SettingsTabKey;

type Props = {
  open: boolean;
  onClose: () => void;
  locale: Locale;
  user: AuthUser | null;
  onUserUpdated?: (user: AuthUser) => void;
  onLocaleChange?: (locale: Locale) => void;
  onMessage?: (message: string) => void;
};

const COOKIE_QR_PLATFORMS = new Set<CookiePlatform>(["bilibili"]);

const COOKIE_PLATFORMS: { key: CookiePlatform; label: string }[] = [
  { key: "youtube", label: "YouTube" },
  { key: "bilibili", label: "哔哩哔哩" },
  { key: "zhihu", label: "知乎" },
  { key: "zlibrary", label: "Z-Library" },
  { key: "xiaohongshu", label: "小红书" },
  { key: "twitter", label: "X / Twitter" }
];

const SUB_PLATFORMS: { key: "bilibili" | "youtube" | "zhihu" | "twitter"; label: string }[] = [
  { key: "bilibili", label: "哔哩哔哩" },
  { key: "youtube", label: "YouTube" },
  { key: "zhihu", label: "知乎" },
  { key: "twitter", label: "X / Twitter" }
];

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

function cookieDotClass(status: CookieStatus | undefined): string {
  const acc = status?.account;
  if (!status?.exists) {
    return "bg-border";
  }
  if (acc?.valid === true) {
    return "bg-emerald-500";
  }
  if (acc?.valid === false) {
    return "bg-red-500";
  }
  return "bg-amber-400";
}

function cookieFailureHint(locale: Locale, detail?: string | null): string {
  const source = String(detail || "").toLowerCase();
  if (/429|too many|rate.?limit|network|proxy|timeout|timed out|connection|connect|dns|fetch|ssl|certificate|socket|econn/.test(source)) {
    return L(locale, "网络问题，请检查代理后重试", "Network problem — check your proxy and try again");
  }
  if (/captcha|验证码|security verification|安全验证|风控|blocked automated|unhuman/.test(source)) {
    return L(locale, "平台要求安全验证，请稍后重试或使用扫码登录", "The platform requires security verification — try later or use QR sign-in");
  }
  if (/cookie|login|sign in|未登录|过期|失效|访客|缺少 google/.test(source)) {
    return L(locale, "登录状态无效，请重新导入已登录页面的 Cookie", "Sign-in is invalid — re-import cookies from a logged-in page");
  }
  return L(locale, "验证失败，请重新导入 Cookie 后重试", "Verification failed — re-import cookies and try again");
}

function cookieAccountSubtitle(status: CookieStatus | undefined, locale: Locale): string {
  if (!status?.exists) {
    return L(locale, "未配置", "Not configured");
  }
  const acc = status.account;
  if (!acc) {
    return L(locale, `${status.count} 条 Cookie · 正在检测`, `${status.count} cookies · checking`);
  }
  if (acc.valid === true) {
    const detail = acc.detail?.trim();
    const name = acc.account_name?.trim();
    const id = acc.account_id?.trim();
    const identity = name && name !== "YouTube" ? (id && name !== id ? `${name} · ${id}` : name) : id;
    const missing: string[] = [];
    if (!identity) missing.push(L(locale, "用户名", "username"));
    if (!acc.avatar_url?.trim()) missing.push(L(locale, "头像", "avatar"));
    if (missing.length > 0) {
      return `${identity || L(locale, "Cookie 有效", "Cookies valid")} · ${L(locale, "账号信息不完整，请重新导出已登录页面的 Cookie", "Account details are incomplete — re-export cookies from a logged-in page")}`;
    }
    if (detail && detail.includes("订阅频道")) {
      return `${identity} · ${detail}`;
    }
    return identity || detail || L(locale, "Cookie 有效", "Cookies valid");
  }
  if (acc.valid === false) {
    return cookieFailureHint(locale, acc.detail);
  }
  return L(locale, "尚未完成验证，请点击验证", "Verification incomplete — click Verify to check again");
}

function cookieStatusTextClass(status: CookieStatus | undefined): string {
  if (status?.account?.valid === false) return "text-red-600";
  if (status?.account?.valid === null) return "text-amber-600";
  return "text-muted";
}

function cookieImportMessage(
  locale: Locale,
  count: number,
  account?: CookieAccountInfo | null
): string {
  if (account?.valid === true) {
    const detail = account.detail?.trim();
    const who = account.account_name?.trim() || account.account_id || "";
    const label =
      detail && (who === "YouTube" || !who)
        ? detail
        : who
          ? L(locale, `已识别账号 ${who}`, `signed in as ${who}`)
          : detail || "";
    return L(
      locale,
      `已导入 ${count} 条${label ? ` · ${label}` : ""}`,
      `Imported ${count} cookies${label ? ` · ${label}` : ""}`
    );
  }
  if (account?.valid === false && account.detail) {
    return L(
      locale,
      `已导入 ${count} 条，但${cookieFailureHint(locale, account.detail)}`,
      `Imported ${count} cookies, but ${cookieFailureHint(locale, account.detail)}`
    );
  }
  return L(locale, `已导入 ${count} 条 Cookie`, `Imported ${count} cookies`);
}

export function SettingsCenter(props: Props): JSX.Element | null {
  const { open, onClose, locale, user } = props;
  const [tab, setTab] = useState<TabKey>("general");

  useEffect(() => {
    if (!open) {
      return;
    }
    const requested = consumeRequestedSettingsTab();
    if (requested) {
      setTab(requested);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const tabs: { key: TabKey; label: string; icon: JSX.Element }[] = [
    { key: "general", label: L(locale, "应用", "App"), icon: <SlidersHorizontal className="h-4 w-4" /> },
    { key: "account", label: L(locale, "账号", "Account"), icon: <UserCircle2 className="h-4 w-4" /> },
    { key: "chats", label: L(locale, "聊天", "Chats"), icon: <MessageCircle className="h-4 w-4" /> },
    { key: "subscriptions", label: L(locale, "同步", "Sync"), icon: <Cookie className="h-4 w-4" /> },
    { key: "ai", label: L(locale, "AI", "AI"), icon: <Bot className="h-4 w-4" /> },
    { key: "books", label: L(locale, "图书", "Books"), icon: <BookOpen className="h-4 w-4" /> },
    { key: "papers", label: "Paper", icon: <FileText className="h-4 w-4" /> },
    { key: "push", label: L(locale, "推送", "Delivery"), icon: <KeyRound className="h-4 w-4" /> },
    { key: "about", label: L(locale, "关于", "About"), icon: <Info className="h-4 w-4" /> }
  ];

  const tabGroups: { label: string; keys: TabKey[] }[] = [
    {
      label: L(locale, "应用", "App"),
      keys: ["general"]
    },
    {
      label: L(locale, "连接", "Connections"),
      keys: ["account", "chats"]
    },
    {
      label: L(locale, "内容", "Content"),
      keys: ["subscriptions", "books", "papers"]
    },
    {
      label: L(locale, "服务", "Services"),
      keys: ["ai", "push"]
    },
    {
      label: L(locale, "其他", "Other"),
      keys: ["about"]
    }
  ];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[var(--on1y-overlay)] p-4">
      <div className="flex h-[600px] max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
        <aside className="flex w-48 shrink-0 flex-col border-r border-border bg-panel/80 p-3">
          <div className="px-2 py-2 text-sm font-semibold tracking-tight text-foreground">
            {L(locale, "设置", "Settings")}
          </div>
          <nav className="mt-1 space-y-3">
            {tabGroups.map((group) => (
              <div key={group.label}>
                <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
                  {group.label}
                </div>
                <div className="space-y-0.5">
                  {group.keys.map((key) => {
                    const item = tabs.find((candidate) => candidate.key === key);
                    if (!item) {
                      return null;
                    }
                    return (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => setTab(item.key)}
                        className={`flex w-full items-center gap-2.5 rounded-lg border-l-2 py-2 pl-2 pr-2.5 text-left text-sm transition ${
                          tab === item.key
                            ? "border-accent bg-surface font-medium text-foreground shadow-sm"
                            : "border-transparent text-muted hover:bg-surface/70 hover:text-foreground"
                        }`}
                      >
                        {item.icon}
                        <span className="truncate">{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
          <div className="mt-auto px-2 py-2 text-[11px] text-muted">
            {user ? `@${user.username}` : ""}
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">
              {tabs.find((t) => t.key === tab)?.label}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted transition hover:bg-soft hover:text-foreground"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 scrollbar-thin">
            {tab === "general" ? (
              <GeneralTab
                locale={locale}
                onClose={onClose}
                onLocaleChange={props.onLocaleChange}
                onMessage={props.onMessage}
              />
            ) : null}
            {tab === "account" ? (
              <AccountTab locale={locale} user={user} onUserUpdated={props.onUserUpdated} onMessage={props.onMessage} />
            ) : null}
            {tab === "chats" ? (
              <ChatsTab locale={locale} onMessage={props.onMessage} />
            ) : null}
            {tab === "subscriptions" ? (
              <SubscriptionsTab locale={locale} onClose={onClose} onMessage={props.onMessage} />
            ) : null}
            {tab === "ai" ? <AiTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "books" ? <BooksTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "papers" ? <PapersTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "push" ? <PushTab locale={locale} onMessage={props.onMessage} /> : null}
            {tab === "about" ? <AboutTab locale={locale} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldLabel(props: { children: React.ReactNode }): JSX.Element {
  return <span className="mb-1.5 block text-xs font-medium text-muted">{props.children}</span>;
}

function SegmentedControl<T extends string>(props: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}): JSX.Element {
  return (
    <div className="inline-flex overflow-hidden rounded-lg border border-border text-sm">
      {props.options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => props.onChange(option.value)}
          className={`px-3 py-2 transition ${
            props.value === option.value
              ? "bg-inverse text-inverse-foreground"
              : "bg-surface text-muted hover:bg-soft"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ToggleRow(props: {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}): JSX.Element {
  return (
    <label className="flex items-start justify-between gap-4 rounded-lg border border-border bg-panel/60 px-3 py-3">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">{props.label}</span>
        {props.description ? (
          <span className="mt-1 block text-xs leading-relaxed text-muted">{props.description}</span>
        ) : null}
      </span>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 accent-accent"
        checked={props.checked}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)}
      />
    </label>
  );
}

function GeneralTab(props: {
  locale: Locale;
  onClose?: () => void;
  onLocaleChange?: (locale: Locale) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [language, setLanguage] = useState<Locale>(locale);
  const [appearance, setAppearance] = useState<AppearanceMode>("system");
  const [closeAction, setCloseAction] = useState<"hide" | "quit">("quit");
  const [dataDirInput, setDataDirInput] = useState("");
  const [autostart, setAutostartEnabled] = useState(false);
  const [autostartSupported, setAutostartSupported] = useState(false);
  const [desktop, setDesktop] = useState<DesktopAppStatus | null>(null);
  const [browsingDataDir, setBrowsingDataDir] = useState(false);
  const [proxyMode, setProxyMode] = useState<"auto" | "manual" | "off">("auto");
  const [manualProxy, setManualProxy] = useState("");
  const [networkStatus, setNetworkStatus] = useState<NetworkSettingsView | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);
  const [alertEnabled, setAlertEnabled] = useState(true);
  const [alertCooldown, setAlertCooldown] = useState(300);
  const [alertWebhook, setAlertWebhook] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [profile, status, network, syncSettings] = await Promise.all([
          getUserProfile(),
          getDesktopAppStatus(),
          getNetworkSettings(),
          getSyncSettings()
        ]);
        if (cancelled) {
          return;
        }
        const appLocale = profile.app?.locale === "en" ? "en" : "zh";
        setLanguage(appLocale);
        const appAppearance = profile.app?.appearance;
        setAppearance(
          appAppearance === "light" || appAppearance === "dark" || appAppearance === "system"
            ? appAppearance
            : "system"
        );
        setCloseAction(status.close_window_action === "quit" ? "quit" : "hide");
        setDataDirInput(status.data_dir_override ?? status.data_dir ?? "");
        setAutostartEnabled(status.autostart_enabled);
        setAutostartSupported(status.autostart_supported);
        setDesktop(status);
        setNetworkStatus(network);
        setProxyMode(network.proxy_mode === "manual" || network.proxy_mode === "off" ? network.proxy_mode : "auto");
        setManualProxy(network.manual_proxy ?? "");
        setAlertEnabled(Boolean(syncSettings.alert_enabled));
        setAlertCooldown(syncSettings.alert_cooldown_seconds);
        setAlertWebhook(syncSettings.alert_webhook_url ?? "");
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once when tab opens
  }, []);

  function onAppearanceChange(mode: AppearanceMode): void {
    setAppearance(mode);
    persistStoredAppearance(mode);
    notifyAppearanceChange(mode);
    void patchUserProfile({ appearance: mode }).catch((err) => {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    });
  }

  function onCloseActionChange(action: "hide" | "quit"): void {
    setCloseAction(action);
    void patchDesktopPrefs({ close_window_action: action }).catch((err) => {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    });
  }

  async function onBrowseDataDir(): Promise<void> {
    setBrowsingDataDir(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      setDataDirInput(picked);
      await patchDesktopPrefs({ data_dir_override: picked });
      props.onMessage?.(
        L(locale, "数据目录已保存，请重启 On1y 后生效", "Data folder saved — restart On1y to apply")
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowsingDataDir(false);
    }
  }

  async function saveGeneral(): Promise<void> {
    setSaving(true);
    try {
      const nextDataDir = dataDirInput.trim();
      const dataDirChanged =
        nextDataDir.length > 0 && nextDataDir !== (desktop?.data_dir ?? "").trim();
      const [network] = await Promise.all([
        saveNetworkSettings({
          proxy_mode: proxyMode,
          manual_proxy: manualProxy
        }),
        saveSyncSettings({
          alert_enabled: alertEnabled,
          alert_cooldown_seconds: alertCooldown,
          alert_webhook_url: alertWebhook.trim()
        }),
        patchUserProfile({
          locale: language,
          appearance
        }),
        patchDesktopPrefs({
          close_window_action: closeAction,
          ...(dataDirChanged ? { data_dir_override: nextDataDir } : {})
        })
      ]);
      setNetworkStatus(network);
      persistStoredLocale(language);
      persistStoredAppearance(appearance);
      notifyAppearanceChange(appearance);
      props.onLocaleChange?.(language);
      props.onMessage?.(
        dataDirChanged
          ? L(locale, "通用设置已保存，请重启 On1y 使数据目录生效", "Settings saved — restart On1y to apply the data folder")
          : L(locale, "通用设置已保存", "General settings saved")
      );
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
      if (enabled) {
        await patchUserProfile({ open_browser_on_start: true });
      }
      props.onMessage?.(
        enabled
          ? L(locale, "已开启登录时自动启动（将直接显示工作台）", "Autostart enabled — workspace will open on sign-in")
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
          {L(locale, "外观", "Appearance")}
        </h3>
        <SegmentedControl
          value={appearance}
          onChange={onAppearanceChange}
          options={[
            { value: "light", label: L(locale, "浅色", "Light") },
            { value: "dark", label: L(locale, "深色", "Dark") },
            { value: "system", label: L(locale, "跟随系统", "System") }
          ]}
        />
        <p className="text-[11px] leading-relaxed text-neutral-500">
          {L(
            locale,
            "深色为低饱和海军蓝调，偏沉稳专业的电影感光影。",
            "Dark mode uses muted navy tones with a restrained, cinematic look."
          )}
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "语言", "Language")}
        </h3>
        <SegmentedControl
          value={language}
          onChange={setLanguage}
          options={[
            { value: "zh", label: "中文" },
            { value: "en", label: "English" }
          ]}
        />
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "网络 / YouTube 代理", "Network / YouTube proxy")}
        </h3>
        <SegmentedControl
          value={proxyMode}
          onChange={(value) => setProxyMode(value as "auto" | "manual" | "off")}
          options={[
            { value: "auto", label: L(locale, "自动", "Auto") },
            { value: "manual", label: L(locale, "手动", "Manual") },
            { value: "off", label: L(locale, "关闭", "Off") }
          ]}
        />
        {proxyMode === "manual" ? (
          <input
            className={inputClass}
            value={manualProxy}
            onChange={(e) => setManualProxy(e.target.value)}
            placeholder="http://127.0.0.1:7890"
          />
        ) : null}
        <p className="text-[11px] leading-relaxed text-neutral-500">
          {L(
            locale,
            "自动模式会读取 Windows 系统代理，并尝试常见本地端口（Clash/V2Ray）。用于 YouTube 字幕与频道同步。",
            "Auto reads Windows system proxy and probes common local ports (Clash/V2Ray). Used for YouTube subtitles and channel sync."
          )}
        </p>
        {networkStatus?.effective_proxy ? (
          <p className="text-[11px] text-neutral-600">
            {L(locale, "当前生效", "Active")}: <span className="font-mono">{networkStatus.effective_proxy}</span>
          </p>
        ) : null}
        {networkStatus?.system_proxy ? (
          <p className="text-[11px] text-neutral-500">
            {L(locale, "系统代理", "System")}: <span className="font-mono">{networkStatus.system_proxy}</span>
          </p>
        ) : null}
        <button
          type="button"
          className={`${ghostBtn} px-3 py-1.5 text-xs`}
          disabled={testingProxy}
          onClick={() => {
            const target =
              proxyMode === "manual"
                ? manualProxy
                : networkStatus?.effective_proxy ?? networkStatus?.system_proxy ?? "";
            if (!target.trim()) {
              props.onMessage?.(L(locale, "没有可测试的代理地址", "No proxy to test"));
              return;
            }
            setTestingProxy(true);
            void testNetworkProxy(target.trim())
              .then((result) => {
                props.onMessage?.(
                  result.ok
                    ? L(locale, `代理可用 (${result.status_code})`, `Proxy OK (${result.status_code})`)
                    : L(locale, `代理不可用: ${result.error ?? "failed"}`, `Proxy failed: ${result.error ?? "failed"}`)
                );
              })
              .catch((err) => props.onMessage?.(err instanceof Error ? err.message : String(err)))
              .finally(() => setTestingProxy(false));
          }}
        >
          {testingProxy ? L(locale, "测试中…", "Testing…") : L(locale, "测试代理", "Test proxy")}
        </button>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "同步提示", "Sync notices")}
        </h3>
        <ToggleRow
          label={L(locale, "同步异常提示", "Sync issue notices")}
          description={L(
            locale,
            "同步受阻时在工作台顶部显示一行提示。",
            "Show a one-line notice at the top when sync is blocked."
          )}
          checked={alertEnabled}
          onChange={setAlertEnabled}
        />
        {alertEnabled ? (
          <div className="space-y-3 pl-1">
            <div className="space-y-2">
              <FieldLabel>{L(locale, "重复提示间隔（秒）", "Repeat interval (seconds)")}</FieldLabel>
              <input
                type="number"
                min={60}
                max={3600}
                className={`${inputClass} w-32`}
                value={alertCooldown}
                onChange={(e) => setAlertCooldown(Math.max(60, Math.min(3600, Number(e.target.value) || 300)))}
              />
            </div>
            <div className="space-y-2">
              <FieldLabel>{L(locale, "Webhook（可选）", "Webhook (optional)")}</FieldLabel>
              <input
                className={inputClass}
                value={alertWebhook}
                onChange={(e) => setAlertWebhook(e.target.value)}
                placeholder="https://..."
              />
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "关闭窗口", "Close window")}
        </h3>
        <SegmentedControl
          value={closeAction}
          onChange={onCloseActionChange}
          options={[
            { value: "quit", label: L(locale, "退出程序", "Quit app") },
            { value: "hide", label: L(locale, "最小化到托盘", "Hide to tray") }
          ]}
        />
        <p className="text-[11px] leading-relaxed text-neutral-500">
          {L(
            locale,
            "仅桌面版生效，切换后立即保存。点关闭按钮时隐藏到托盘，或完全退出 On1y。",
            "Desktop app only; saves immediately. Close button hides to tray or quits On1y."
          )}
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "数据存储", "Data storage")}
        </h3>
        <FieldLabel>{L(locale, "数据目录", "Data folder")}</FieldLabel>
        <div className="flex gap-2">
          <input
            className={`${inputClass} min-w-0 flex-1`}
            value={dataDirInput}
            onChange={(e) => setDataDirInput(e.target.value)}
            placeholder={desktop?.data_dir ?? "D:\\On1y\\data"}
          />
          <button
            type="button"
            className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
            disabled={browsingDataDir || saving}
            onClick={() => void onBrowseDataDir()}
          >
            {browsingDataDir ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FolderOpen className="h-4 w-4" />
            )}
            {L(locale, "浏览…", "Browse…")}
          </button>
        </div>
        <p className="text-[11px] leading-relaxed text-neutral-500">
          {L(
            locale,
            "知识库、Cookie、订阅与 LLM 配置均保存在此目录（按用户分子目录）。网页版浏览会打开本机文件夹选择（需 on1y serve 与浏览器在同一台电脑）；修改后需重启。",
            "Knowledge base, cookies, subscriptions, and LLM settings live here (per-user subfolders). Browse opens a folder dialog on the machine running on1y serve; restart after changing."
          )}
        </p>
        <p className="rounded-lg border border-border bg-soft/40 px-3 py-3 text-xs leading-relaxed text-muted">
          {L(locale, "账户备份、历史内容和 Cookie 迁移已统一放在「账号 → 数据」中。", "Account backup, history, and cookie migration are now under Account → Data.")}
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "新手引导", "Getting started")}
        </h3>
        <div className="rounded-lg border border-neutral-100 bg-neutral-50/60 px-3 py-3">
          <p className="text-sm font-medium text-neutral-900">
            {L(locale, "功能引导", "Feature tour")}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-neutral-500">
            {L(
              locale,
              "查看 On1y 工作台、订阅、Cookie、初始同步、AI 等完整介绍。",
              "Walk through workspace, subscriptions, cookies, initial sync, AI, and more."
            )}
          </p>
          <button
            type="button"
            onClick={() => {
              props.onClose?.();
              showFirstRunGuide();
            }}
            className="mt-3 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-800 hover:bg-neutral-50"
          >
            {L(locale, "打开功能引导", "Open feature tour")}
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
            "开启后登录 Windows 会自动启动 On1y 并打开工作台。",
            "When enabled, On1y starts on Windows sign-in and opens the workspace."
          )}
          checked={autostart}
          disabled={!autostartSupported}
          onChange={(v) => void onAutostartToggle(v)}
        />
        <div className="flex justify-end">
          <button type="button" className={primaryBtn} disabled={saving} onClick={() => void saveGeneral()}>
            {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
          </button>
        </div>
      </section>

    </div>
  );
}

function ChatsTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  return (
    <div className="space-y-6">
      <section className="space-y-1">
        <h3 className="text-sm font-semibold text-foreground">
          {L(locale, "聊天归档", "Chat archive")}
        </h3>
        <p className="text-xs leading-relaxed text-muted">
          {L(
            locale,
            "连接 Telegram 后，On1y 会定时拉取选中聊天并归档到「聊天」专栏。",
            "Connect Telegram to sync selected chats into the Chats collection."
          )}
        </p>
      </section>
      <TelegramSettingsPanel locale={locale} onMessage={props.onMessage} />
    </div>
  );
}

function AboutTab(props: { locale: Locale }): JSX.Element {
  const { locale } = props;

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <img src="/on1y-logo.png" alt="On1y" className="h-12 w-12" />
        <h3 className="text-lg font-semibold text-neutral-900">On1y</h3>
        <p className="text-sm leading-relaxed text-neutral-600">
          {L(locale, "欢迎加入。", "Welcome aboard.")}
        </p>
      </section>

      <p className="text-[11px] text-neutral-400">
        <a
          href="https://github.com/S1jinCheng/ON1Y"
          target="_blank"
          rel="noreferrer"
          className="underline hover:text-neutral-600"
        >
          github.com/S1jinCheng/ON1Y
        </a>
      </p>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none transition focus:border-foreground disabled:opacity-50";
const primaryBtn =
  "rounded-lg bg-inverse px-4 py-2 text-sm font-medium text-inverse-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50";
const ghostBtn =
  "rounded-lg border border-border bg-surface px-4 py-2 text-sm text-muted transition hover:bg-soft disabled:opacity-50";

type AccountCenterSection = "overview" | "data";

function AccountTab(props: {
  locale: Locale;
  user: AuthUser | null;
  onUserUpdated?: (user: AuthUser) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const [section, setSection] = useState<AccountCenterSection>("overview");
  const { locale } = props;

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-panel/60 p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-inverse text-base font-semibold text-inverse-foreground">
            {(props.user?.display_name || props.user?.username || "?").charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate text-base font-semibold text-foreground">
              {props.user?.display_name || props.user?.username || L(locale, "本机账户", "Local account")}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted">
              {props.user ? `@${props.user.username}` : L(locale, "当前设备上的个人数据", "Personal data on this device")}
            </div>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          {L(
            locale,
            "账户中心管理个人资料、账户切换和当前账户的数据。它们都保存在本机，不会自动上传到云端。",
            "Manage your profile, account switching, and account data here. Everything stays on this device unless you export it."
          )}
        </p>
      </div>

      <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-soft/40 p-1">
        {(
          [
            ["overview", L(locale, "概览", "Overview")],
            ["data", L(locale, "数据", "Data")]
          ] as [AccountCenterSection, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setSection(key)}
            className={`rounded-md px-3 py-1.5 text-xs transition ${
              section === key ? "bg-surface font-medium text-foreground shadow-sm" : "text-muted hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {section === "overview" ? <AccountOverviewTab {...props} /> : <AccountDataTab locale={locale} onMessage={props.onMessage} />}
    </div>
  );
}

function AccountOverviewTab(props: {
  locale: Locale;
  user: AuthUser | null;
  onUserUpdated?: (user: AuthUser) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [displayName, setDisplayName] = useState(props.user?.display_name ?? "");
  const [email, setEmail] = useState(props.user?.email ?? "");
  const [savingProfile, setSavingProfile] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [singleUserMode, setSingleUserMode] = useState(false);
  const [allowRegistration, setAllowRegistration] = useState(true);
  const [knownUsers, setKnownUsers] = useState<AuthUser[]>([]);
  const [switchUsername, setSwitchUsername] = useState("");
  const [switchPassword, setSwitchPassword] = useState("");
  const [switching, setSwitching] = useState(false);
  const [recentUsernames, setRecentUsernames] = useState<string[]>([]);

  useEffect(() => {
    setDisplayName(props.user?.display_name ?? "");
    setEmail(props.user?.email ?? "");
  }, [props.user]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [status, listed] = await Promise.all([fetchAuthStatus(), fetchAuthUsers()]);
        if (cancelled) {
          return;
        }
        setAuthRequired(status.auth_required);
        setSingleUserMode(status.single_user_mode);
        setAllowRegistration(status.allow_registration);
        setKnownUsers(listed.users);
        setRecentUsernames(getRecentAuthUsernames());
      } catch {
        /* optional for single-user mode */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  async function handleSwitchAccount(event: FormEvent): Promise<void> {
    event.preventDefault();
    const username = switchUsername.trim();
    if (!username || !switchPassword) {
      props.onMessage?.(L(locale, "请输入用户名和密码", "Enter username and password"));
      return;
    }
    setSwitching(true);
    try {
      await switchAccount(username, switchPassword);
      props.onMessage?.(L(locale, "已切换账号，正在刷新…", "Switched account, reloading…"));
      window.location.assign("/");
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSwitching(false);
    }
  }

  function goLogin(mode: "login" | "register" = "login"): void {
    logout();
    const suffix = mode === "register" ? "?mode=register" : "";
    window.location.assign(`/login${suffix}`);
  }

  const currentId = props.user?.id;
  const otherUsers = knownUsers.filter((u) => u.id !== currentId);
  const quickNames = [
    ...recentUsernames,
    ...otherUsers.map((u) => u.username).filter((name) => !recentUsernames.includes(name))
  ].filter((name) => name.toLowerCase() !== (props.user?.username ?? "").toLowerCase());

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "当前账号", "Current account")}
        </h3>
        <div className="rounded-lg border border-neutral-100 bg-neutral-50/60 px-3 py-3 text-sm">
          <div className="font-medium text-neutral-900">
            {props.user?.display_name || props.user?.username || L(locale, "未登录", "Not signed in")}
          </div>
          {props.user ? (
            <div className="mt-1 space-y-0.5 text-xs text-neutral-500">
              <div>
                @{props.user.username} · ID {props.user.id}
              </div>
              {props.user.email ? <div>{props.user.email}</div> : null}
            </div>
          ) : null}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "个人资料", "Profile")}
        </h3>
        <div>
          <FieldLabel>{L(locale, "显示名称", "Display name")}</FieldLabel>
          <input className={inputClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <FieldLabel>{L(locale, "邮箱", "Email")}</FieldLabel>
          <input
            className={inputClass}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </div>
        <div className="flex justify-end">
          <button type="button" className={primaryBtn} disabled={savingProfile} onClick={() => void saveProfile()}>
            {savingProfile ? L(locale, "保存中…", "Saving…") : L(locale, "保存资料", "Save profile")}
          </button>
        </div>
      </section>

      {authRequired && !singleUserMode ? (
        <section className="space-y-3 border-t border-neutral-100 pt-6">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
            {L(locale, "切换账号", "Switch account")}
          </h3>
          <p className="text-xs leading-relaxed text-neutral-500">
            {L(
              locale,
              "切换后将加载该用户独立的知识库、Cookie 与订阅设置。本机共 " +
                String(knownUsers.length) +
                " 个账号。",
              `After switching you will see that user's knowledge base, cookies, and subscriptions. ${knownUsers.length} account(s) on this machine.`
            )}
          </p>

          {otherUsers.length > 0 ? (
            <div className="space-y-2">
              <FieldLabel>{L(locale, "本机其他账号", "Other accounts on this device")}</FieldLabel>
              <div className="flex flex-wrap gap-2">
                {otherUsers.map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      switchUsername === u.username
                        ? "border-black bg-black text-white"
                        : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-400"
                    }`}
                    onClick={() => {
                      setSwitchUsername(u.username);
                      setSwitchPassword("");
                    }}
                  >
                    {u.display_name || u.username}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {quickNames.length > 0 ? (
            <div className="space-y-2">
              <FieldLabel>{L(locale, "最近使用", "Recent")}</FieldLabel>
              <div className="flex flex-wrap gap-2">
                {quickNames.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="rounded-full border border-neutral-200 bg-white px-3 py-1 text-xs text-neutral-600 hover:border-neutral-400"
                    onClick={() => {
                      setSwitchUsername(name);
                      setSwitchPassword("");
                    }}
                  >
                    @{name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <form className="space-y-3" onSubmit={(e) => void handleSwitchAccount(e)}>
            <div>
              <FieldLabel>{L(locale, "用户名", "Username")}</FieldLabel>
              <input
                className={inputClass}
                value={switchUsername}
                onChange={(e) => setSwitchUsername(e.target.value)}
                autoComplete="username"
                placeholder="alice"
              />
            </div>
            <div>
              <FieldLabel>{L(locale, "密码", "Password")}</FieldLabel>
              <input
                className={inputClass}
                type="password"
                value={switchPassword}
                onChange={(e) => setSwitchPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                className="rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-600 hover:bg-neutral-50"
                onClick={() => goLogin("login")}
              >
                {L(locale, "退出并登录其他账号", "Sign out & pick account")}
              </button>
              {allowRegistration ? (
                <button
                  type="button"
                  className="rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-600 hover:bg-neutral-50"
                  onClick={() => goLogin("register")}
                >
                  {L(locale, "注册新账号", "Register new account")}
                </button>
              ) : null}
              <button type="submit" className={primaryBtn} disabled={switching}>
                {switching ? L(locale, "切换中…", "Switching…") : L(locale, "切换到此账号", "Switch to this account")}
              </button>
            </div>
          </form>
        </section>
      ) : singleUserMode ? (
        <section className="space-y-2 border-t border-neutral-100 pt-6 text-xs text-neutral-500">
          <p>
            {L(
              locale,
              "当前为安装版单用户模式，数据与设置均保存在本机唯一账号下。",
              "Desktop single-user mode: all data and settings use one local account."
            )}
          </p>
        </section>
      ) : (
        <section className="space-y-2 border-t border-neutral-100 pt-6 text-xs text-neutral-500">
          <p>
            {L(
              locale,
              "当前为单用户免登录模式（ON1Y_AUTH_REQUIRED=false）。要测试多用户，请在 .env  中设置 ON1Y_AUTH_REQUIRED=true 并重启 on1y serve。",
              "Single-user mode (ON1Y_AUTH_REQUIRED=false). Set ON1Y_AUTH_REQUIRED=true in .env and restart on1y serve to test multi-user."
            )}
          </p>
        </section>
      )}
    </div>
  );
}

function AccountPlatformsTab(props: {
  locale: Locale;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [statuses, setStatuses] = useState<CookieStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<CookiePlatform | null>(null);
  const [qrLogin, setQrLogin] = useState<{ platform: CookiePlatform; label: string } | null>(null);

  async function reload(fullVerify = false): Promise<void> {
    setLoading(true);
    try {
      const result = await getCookieStatuses(true, { quick: !fullVerify });
      setStatuses(result.platforms);
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // Load once when the account center opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function paste(platform: CookiePlatform): Promise<void> {
    setBusy(platform);
    try {
      const result = await importCookieFromClipboard(platform);
      props.onMessage?.(cookieImportMessage(locale, result.count, result.account));
      await reload(true);
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function verify(platform: CookiePlatform): Promise<void> {
    setBusy(platform);
    try {
      const result = await verifyCookiePlatform(platform);
      setStatuses((prev) => prev.map((row) => row.platform === platform ? { ...row, account: result.account } : row));
      const account = result.account;
      props.onMessage?.(
        account.valid === true
          ? L(locale, `验证通过：${account.account_name || account.account_id || platform}`, `Verified: ${account.account_name || account.account_id || platform}`)
          : cookieFailureHint(locale, account.detail)
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove(platform: CookiePlatform): Promise<void> {
    setBusy(platform);
    try {
      await deleteCookieFile(platform);
      props.onMessage?.(L(locale, "已删除该平台登录记录", "Platform sign-in removed"));
      await reload();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">{L(locale, "平台账号", "Platform accounts")}</h3>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              {L(locale, "这些登录记录只属于当前本机账户。页面打开后会自动检查状态。", "These sign-ins belong only to the current local account. Status is checked when this page opens.")}
            </p>
          </div>
          <button type="button" className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`} disabled={loading} onClick={() => void reload(true)}>
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {L(locale, "刷新", "Refresh")}
          </button>
        </div>
        <div className="rounded-lg border border-border bg-soft/40 px-3 py-2.5 text-[11px] leading-relaxed text-muted">
          {L(locale, "B 站支持扫码登录；其他平台可用 Cookie-Editor 导出 JSON 后粘贴。", "Bilibili supports QR sign-in; for other platforms, export JSON with Cookie-Editor and paste it here.")}
        </div>
      </section>

      <div className="space-y-2">
        {COOKIE_PLATFORMS.map((platform) => {
          const status = statuses.find((row) => row.platform === platform.key);
          const account = status?.account;
          const avatar = account?.avatar_url?.trim();
          const exists = status?.exists ?? false;
          return (
            <div key={platform.key} className="rounded-xl border border-border bg-surface px-3 py-3">
              <div className="flex items-center gap-3">
                <div className="relative shrink-0">
                  {avatar ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={avatar} alt="" className="h-10 w-10 rounded-full border border-border object-cover" referrerPolicy="no-referrer" />
                  ) : (
                    <div className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-soft text-muted"><UserCircle2 className="h-5 w-5" /></div>
                  )}
                  <span className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${cookieDotClass(status)}`} aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">{platform.label}</div>
                  <div className={`truncate text-[11px] leading-relaxed ${cookieStatusTextClass(status)}`}>
                    {status ? cookieAccountSubtitle(status, locale) : loading ? L(locale, "正在检测…", "Checking…") : L(locale, "未配置", "Not configured")}
                  </div>
                  {status?.updated_at ? <div className="text-[10px] text-muted/70">{L(locale, "更新", "Updated")}: {status.updated_at.replace("T", " ")}</div> : null}
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                  {COOKIE_QR_PLATFORMS.has(platform.key) ? (
                    <button type="button" className={`${ghostBtn} px-2.5 py-1.5 text-xs`} disabled={busy === platform.key} onClick={() => setQrLogin({ platform: platform.key, label: platform.label })}>
                      <QrCode className="mr-1 inline h-3.5 w-3.5" />{L(locale, "扫码", "QR")}
                    </button>
                  ) : null}
                  <button type="button" className={`${ghostBtn} px-2.5 py-1.5 text-xs`} disabled={busy === platform.key} onClick={() => void paste(platform.key)}>
                    {busy === platform.key ? <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> : <ClipboardPaste className="mr-1 inline h-3.5 w-3.5" />}
                    {L(locale, "更新", "Update")}
                  </button>
                  {exists ? <>
                    <button type="button" className={`${ghostBtn} px-2.5 py-1.5 text-xs`} disabled={busy === platform.key} onClick={() => void verify(platform.key)}><RefreshCw className="mr-1 inline h-3.5 w-3.5" />{L(locale, "验证", "Verify")}</button>
                    <button type="button" className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50" disabled={busy === platform.key} onClick={() => void remove(platform.key)} aria-label={L(locale, "删除", "Delete")}><Trash2 className="h-4 w-4" /></button>
                  </> : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <CookieQrLoginDialog
        locale={locale}
        platform={qrLogin?.platform ?? "bilibili"}
        platformLabel={qrLogin?.label ?? ""}
        open={qrLogin != null}
        onClose={() => setQrLogin(null)}
        onSuccess={() => void reload(true)}
        onMessage={props.onMessage}
      />
    </div>
  );
}

function AccountDataTab(props: {
  locale: Locale;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [archiveExporting, setArchiveExporting] = useState(false);
  const [archiveImporting, setArchiveImporting] = useState(false);
  const [includeSettings, setIncludeSettings] = useState(false);
  const [includeTrash, setIncludeTrash] = useState(false);
  const [conflict, setConflict] = useState<"skip" | "overwrite">("overwrite");
  const archiveImportRef = useRef<HTMLInputElement>(null);

  async function exportArchive(): Promise<void> {
    const options = { includeTrash, includeSettings };
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "").slice(0, 15);
    const filename = `on1y-library-${stamp}.on1y.zip`;
    if (!isDesktopShell()) {
      triggerBrowserFileDownload(buildUserArchiveExportUrl(options), filename);
      props.onMessage?.(L(locale, "正在下载导出文件…", "Downloading export…"));
      return;
    }
    setArchiveExporting(true);
    try {
      const blob = await exportUserArchive(options);
      const savedPath = await saveArchiveFile(filename, new Uint8Array(await blob.arrayBuffer()));
      if (savedPath) props.onMessage?.(L(locale, `账户数据已保存到 ${savedPath}`, `Account data saved to ${savedPath}`));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setArchiveExporting(false);
    }
  }

  async function importArchive(file: File | null): Promise<void> {
    if (!file) return;
    setArchiveImporting(true);
    try {
      const result = await importUserArchive(file, conflict);
      let summary = L(locale, `已导入 ${result.imported} 条，跳过 ${result.skipped} 条`, `Imported ${result.imported}, skipped ${result.skipped}`);
      if (result.subscription_restored > 0 || result.cookies_restored > 0) {
        summary += L(locale, `；订阅设置${result.subscription_restored > 0 ? "已还原" : "未包含"}，Cookie ${result.cookies_restored} 个`, `; subscription ${result.subscription_restored > 0 ? "restored" : "not included"}, ${result.cookies_restored} cookie file(s)`);
      }
      props.onMessage?.(result.error_count > 0 ? `${summary}；${L(locale, "部分失败", "some errors")}: ${result.errors.slice(0, 3).join("; ")}` : summary);
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setArchiveImporting(false);
      if (archiveImportRef.current) archiveImportRef.current.value = "";
    }
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">{L(locale, "账户数据", "Account data")}</h3>
        <p className="text-xs leading-relaxed text-muted">
          {L(locale, "当前账户的知识库、历史内容、订阅和 Cookie 都按账户独立保存。导出文件可用于备份或迁移。", "This account's library, history, subscriptions, and cookies are stored separately. Export a bundle for backup or migration.")}
        </p>
      </section>

      <section className="rounded-xl border border-border bg-panel/60 p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-soft p-2 text-muted"><Download className="h-4 w-4" /></div>
          <div>
            <h4 className="text-sm font-medium text-foreground">{L(locale, "备份与迁移", "Backup & migration")}</h4>
            <p className="mt-1 text-xs leading-relaxed text-muted">{L(locale, "正文、摘要、标签和主题默认包含；Cookie 属于敏感信息，需要单独确认。", "Body text, summaries, tags, and themes are included by default. Cookies are sensitive and require separate confirmation.")}</p>
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <ToggleRow label={L(locale, "同时导出 Cookie 与订阅设置", "Include cookies & subscriptions")} description={L(locale, "仅在迁移到可信设备时开启。", "Enable only when migrating to a trusted device.")} checked={includeSettings} disabled={archiveExporting || archiveImporting} onChange={setIncludeSettings} />
          <ToggleRow label={L(locale, "包含已删除条目", "Include deleted items")} description={L(locale, "默认不包含回收站内容。", "Trash is excluded by default.")} checked={includeTrash} disabled={archiveExporting || archiveImporting} onChange={setIncludeTrash} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`} disabled={archiveExporting || archiveImporting} onClick={() => void exportArchive()}>{archiveExporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{L(locale, "导出账户数据", "Export account data")}</button>
          <button type="button" className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`} disabled={archiveExporting || archiveImporting} onClick={() => archiveImportRef.current?.click()}>{archiveImporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}{L(locale, "导入账户数据", "Import account data")}</button>
          <input ref={archiveImportRef} type="file" accept=".zip,.on1y.zip,application/zip" className="hidden" onChange={(e) => void importArchive(e.target.files?.[0] ?? null)} />
        </div>
        <div className="mt-4">
          <FieldLabel>{L(locale, "导入冲突", "Import conflicts")}</FieldLabel>
          <SegmentedControl value={conflict} onChange={setConflict} options={[{ value: "overwrite", label: L(locale, "覆盖", "Overwrite") }, { value: "skip", label: L(locale, "跳过", "Skip") }]} />
        </div>
      </section>

      <section className="rounded-lg border border-amber-200/70 bg-amber-50/60 px-3 py-3 text-xs leading-relaxed text-amber-900/80">
        {L(locale, "导出的 .on1y.zip 可能包含登录 Cookie，请像保管密码一样保管，不要上传到公共位置。", "An exported .on1y.zip may contain login cookies. Treat it like a password and never upload it publicly.")}
      </section>
    </div>
  );
}

function SubscriptionsTab(props: {
  locale: Locale;
  onClose?: () => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const { locale } = props;
  const [enabled, setEnabled] = useState<string[]>(["bilibili", "youtube", "zhihu"]);
  const [syncSince, setSyncSince] = useState("");
  const [useAiSummary, setUseAiSummary] = useState(true);
  const [statuses, setStatuses] = useState<CookieStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [zhihuFollowMode, setZhihuFollowMode] = useState<"api" | "rss">("api");
  const [zhihuMaxFollowees, setZhihuMaxFollowees] = useState(25);
  const [zhihuMaxPages, setZhihuMaxPages] = useState(2);
  const [zhihuBackfillPages, setZhihuBackfillPages] = useState(5);
  const [zhihuRsshubBase, setZhihuRsshubBase] = useState("http://127.0.0.1:1200");
  const [bilibiliPollMode, setBilibiliPollMode] = useState<"dynamic" | "space">("dynamic");
  const [bilibiliMaxUps, setBilibiliMaxUps] = useState(10);
  const [bilibiliDynamicPages, setBilibiliDynamicPages] = useState(5);
  const [bilibiliDynamicBackfillPages, setBilibiliDynamicBackfillPages] = useState(20);
  const [bilibiliRateBackoff, setBilibiliRateBackoff] = useState(45);
  const [bilibiliRateCooldown, setBilibiliRateCooldown] = useState(90);
  const [rssBackfillMaxItems, setRssBackfillMaxItems] = useState(100);
  const [coldStartBiliDays, setColdStartBiliDays] = useState(3);
  const [coldStartBiliPages, setColdStartBiliPages] = useState(50);
  const [zhihuAutoRefreshFollows, setZhihuAutoRefreshFollows] = useState(false);
  const [youtubeAutoRefresh, setYoutubeAutoRefresh] = useState(false);
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(true);
  const [autoSyncMinutes, setAutoSyncMinutes] = useState(30);
  const [autoSyncBatchSize, setAutoSyncBatchSize] = useState(25);
  const [collectionsSyncEnabled, setCollectionsSyncEnabled] = useState(true);
  const [collectionsSyncSeconds, setCollectionsSyncSeconds] = useState(120);
  const [collectionsSyncPlatforms, setCollectionsSyncPlatforms] = useState<string[]>([
    "bilibili",
    "zhihu",
    "youtube",
    "twitter"
  ]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [settings, syncSettings, cookieMeta] = await Promise.all([
          getSubscriptionSettings(),
          getSyncSettings(),
          getCookieStatuses(true, { quick: true })
        ]);
        if (cancelled) {
          return;
        }
        const platforms = settings.enabled_platforms ?? ["bilibili", "youtube", "zhihu"];
        setEnabled(platforms);
        setSyncSince(pickSyncSinceDisplay(settings, platforms));
        setStatuses(cookieMeta.platforms);
        applySyncSettings(syncSettings);
        setLoading(false);
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
    // Load once on mount; do not depend on props — re-running resets edited syncSince.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applySyncSettings(syncSettings: SyncSettingsView): void {
    setZhihuFollowMode(syncSettings.zhihu_follow_sync_mode === "rss" ? "rss" : "api");
    setZhihuMaxFollowees(syncSettings.zhihu_api_poll_max_followees);
    setZhihuMaxPages(syncSettings.zhihu_api_poll_max_pages);
    setZhihuBackfillPages(syncSettings.zhihu_api_poll_backfill_pages);
    setZhihuRsshubBase(syncSettings.zhihu_rsshub_base ?? "http://127.0.0.1:1200");
    setBilibiliPollMode(syncSettings.bilibili_up_poll_mode === "space" ? "space" : "dynamic");
    setBilibiliMaxUps(syncSettings.bilibili_up_poll_max_ups_per_run);
    setBilibiliDynamicPages(syncSettings.bilibili_dynamic_poll_max_pages);
    setBilibiliDynamicBackfillPages(syncSettings.bilibili_dynamic_poll_backfill_max_pages);
    setBilibiliRateBackoff(syncSettings.bilibili_up_poll_rate_limit_backoff_seconds);
    setBilibiliRateCooldown(syncSettings.bilibili_up_poll_rate_limit_cooldown_seconds);
    setRssBackfillMaxItems(syncSettings.rss_backfill_max_items_per_feed);
    setColdStartBiliDays(syncSettings.cold_start_bilibili_dynamic_days);
    setColdStartBiliPages(syncSettings.cold_start_bilibili_dynamic_max_pages);
    setZhihuAutoRefreshFollows(Boolean(syncSettings.zhihu_auto_refresh_follows));
    setYoutubeAutoRefresh(Boolean(syncSettings.youtube_auto_refresh_channels));
    setAutoSyncEnabled(Boolean(syncSettings.auto_sync_enabled));
    setAutoSyncMinutes(syncSettings.auto_sync_interval_minutes);
    setAutoSyncBatchSize(syncSettings.auto_sync_pipeline_batch_size ?? 25);
    setCollectionsSyncEnabled(Boolean(syncSettings.collections_sync_enabled));
    setCollectionsSyncSeconds(syncSettings.collections_sync_interval_seconds);
    const collectionPlatforms = String(syncSettings.collections_sync_platforms || "")
      .split(",")
      .map((value) => value.trim())
      .filter((value) => SUB_PLATFORMS.some((platform) => platform.key === value));
    setCollectionsSyncPlatforms(
      collectionPlatforms.length > 0 ? collectionPlatforms : SUB_PLATFORMS.map((platform) => platform.key)
    );
  }

  function syncSettingsPayload(): Partial<SyncSettingsView> {
    return {
      zhihu_follow_sync_mode: zhihuFollowMode,
      zhihu_api_poll_max_followees: zhihuMaxFollowees,
      zhihu_api_poll_max_pages: zhihuMaxPages,
      zhihu_api_poll_backfill_pages: zhihuBackfillPages,
      zhihu_rsshub_base: zhihuRsshubBase,
      bilibili_up_poll_mode: bilibiliPollMode,
      bilibili_up_poll_max_ups_per_run: bilibiliMaxUps,
      bilibili_dynamic_poll_max_pages: bilibiliDynamicPages,
      bilibili_dynamic_poll_backfill_max_pages: bilibiliDynamicBackfillPages,
      bilibili_up_poll_rate_limit_backoff_seconds: bilibiliRateBackoff,
      bilibili_up_poll_rate_limit_cooldown_seconds: bilibiliRateCooldown,
      rss_backfill_max_items_per_feed: rssBackfillMaxItems,
      cold_start_bilibili_dynamic_days: coldStartBiliDays,
      cold_start_bilibili_dynamic_max_pages: coldStartBiliPages,
      zhihu_auto_refresh_follows: zhihuAutoRefreshFollows,
      youtube_auto_refresh_channels: youtubeAutoRefresh,
      auto_sync_enabled: autoSyncEnabled,
      auto_sync_interval_minutes: autoSyncMinutes,
      auto_sync_pipeline_batch_size: autoSyncBatchSize,
      collections_sync_enabled: collectionsSyncEnabled,
      collections_sync_interval_seconds: collectionsSyncSeconds,
      collections_sync_platforms: collectionsSyncPlatforms.join(",")
    };
  }

  function toggle(key: string): void {
    setEnabled((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));
  }

  function sincePayload(since: string): {
    bilibili_sync_since: string;
    youtube_sync_since: string;
    zhihu_sync_since: string;
    twitter_sync_since: string;
  } {
    const value = since.trim();
    if (!value) {
      return {
        bilibili_sync_since: "",
        youtube_sync_since: "",
        zhihu_sync_since: "",
        twitter_sync_since: ""
      };
    }
    return {
      bilibili_sync_since: enabled.includes("bilibili") ? value : "",
      youtube_sync_since: enabled.includes("youtube") ? value : "",
      zhihu_sync_since: enabled.includes("zhihu") ? value : "",
      twitter_sync_since: enabled.includes("twitter") ? value : ""
    };
  }

  function pickSyncSinceDisplay(
    settings: Awaited<ReturnType<typeof getSubscriptionSettings>>,
    platforms: string[]
  ): string {
    const dates: string[] = [];
    if (platforms.includes("bilibili") && settings.bilibili_sync_since) {
      dates.push(settings.bilibili_sync_since);
    }
    if (platforms.includes("youtube") && settings.youtube_sync_since) {
      dates.push(settings.youtube_sync_since);
    }
    if (platforms.includes("zhihu") && settings.zhihu_sync_since) {
      dates.push(settings.zhihu_sync_since);
    }
    if (platforms.includes("twitter") && settings.twitter_sync_since) {
      dates.push(settings.twitter_sync_since);
    }
    return dates[0] ?? "";
  }

  async function save(): Promise<void> {
    if (enabled.length === 0) {
      props.onMessage?.(L(locale, "至少选择一个平台", "Select at least one platform"));
      return;
    }
    setSaving(true);
    try {
      const since = syncSince.trim();
      const [syncSaved] = await Promise.all([
        saveSyncSettings(syncSettingsPayload()),
        saveSubscriptionSettings({
          enabled_platforms: enabled,
          ...sincePayload(since)
        })
      ]);
      applySyncSettings(syncSaved);
      props.onMessage?.(
        L(locale, "订阅与同步设置已保存（部分需重启 On1y 后生效）", "Subscription & sync settings saved (restart On1y if needed)")
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function syncNow(): Promise<void> {
    if (enabled.length === 0) {
      props.onMessage?.(L(locale, "至少选择一个平台", "Select at least one platform"));
      return;
    }
    setSyncing(true);
    try {
      const since = syncSince.trim();
      const platforms = enabled.filter((p): p is "bilibili" | "youtube" | "zhihu" | "twitter" =>
        ["bilibili", "youtube", "zhihu", "twitter"].includes(p)
      );
      await Promise.all([
        saveSyncSettings(syncSettingsPayload()),
        saveSubscriptionSettings({
          enabled_platforms: platforms,
          ...sincePayload(since)
        })
      ]);
      const result = await runSubscriptionSync({
        platforms,
        ingest: true,
        use_ai_summary: useAiSummary,
        ingest_limit: 30,
        subtitle_limit: 30,
        distill_limit: useAiSummary ? 50 : 0
      });
      if (!result.started) {
        props.onMessage?.(result.message ?? L(locale, "同步已在进行中", "Sync already running"));
        return;
      }
      props.onMessage?.(result.message ?? L(locale, "已开始同步", "Sync started"));
      const timer = window.setInterval(() => {
        void getSubscriptionSyncStatus().then((status) => {
          if (!status.running) {
            window.clearInterval(timer);
            setSyncing(false);
            if (status.error) {
              props.onMessage?.(status.error);
            } else {
              props.onMessage?.(L(locale, "订阅同步完成", "Subscription sync finished"));
            }
          }
        });
      }, 3000);
    } catch (err) {
      setSyncing(false);
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-6">
      <p className="text-xs leading-relaxed text-muted">
        {L(
          locale,
          "先配置 Cookie 登录态，再选择订阅平台与起始日期。保存后可用「立即同步」拉取新内容。",
          "Configure cookies first, then choose platforms and sync-since date. Save and use Sync now to pull new content."
        )}
      </p>

      <AccountPlatformsTab locale={locale} onMessage={props.onMessage} />

      <InitialSyncSection locale={locale} statuses={statuses} busy={false} onClose={props.onClose} />

      <div className="border-t border-border pt-6" />

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{L(locale, "启用平台", "Enabled platforms")}</h3>
        <div className="space-y-2">
          {SUB_PLATFORMS.map((platform) => (
            <label
              key={platform.key}
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 hover:bg-soft"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border accent-accent"
                checked={enabled.includes(platform.key)}
                onChange={() => toggle(platform.key)}
              />
              <span className="text-sm text-foreground">{platform.label}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{L(locale, "起始日期", "Sync since")}</h3>
        <div className="flex items-center gap-2">
          <input type="date" className={`${inputClass} w-44`} value={syncSince} onChange={(e) => setSyncSince(e.target.value)} />
          {syncSince ? (
            <button type="button" className="text-xs text-muted hover:text-foreground" onClick={() => setSyncSince("")}>
              {L(locale, "清除", "Clear")}
            </button>
          ) : null}
        </div>
        <p className="text-[11px] text-muted">
          {L(locale, "只同步该日期之后发布的内容；留空则不限制。", "Only ingest content published after this date; empty = no limit.")}
        </p>
      </section>

      <ToggleRow
        label={L(locale, "同步时使用 AI 摘要", "Use AI summaries during sync")}
        description={L(
          locale,
          "拉取后自动生成摘要与主题（需配置 AI 页中的 API Key）。",
          "Generate summaries and themes after ingest (requires AI API key)."
        )}
        checked={useAiSummary}
        onChange={setUseAiSummary}
      />

      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className={ghostBtn} disabled={saving || syncing} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
        <button type="button" className={primaryBtn} disabled={saving || syncing} onClick={() => void syncNow()}>
          {syncing ? L(locale, "同步中…", "Syncing…") : L(locale, "立即同步", "Sync now")}
        </button>
      </div>

      <section className="space-y-4 border-t border-border pt-6">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {L(locale, "同步行为", "Sync behavior")}
        </h3>

        <div className="space-y-2">
          <FieldLabel>{L(locale, "知乎关注同步", "Zhihu follow sync")}</FieldLabel>
          <SegmentedControl
            value={zhihuFollowMode}
            onChange={(value) => setZhihuFollowMode(value as "api" | "rss")}
            options={[
              { value: "api", label: L(locale, "API 直连", "API direct") },
              { value: "rss", label: L(locale, "RSS", "RSS") }
            ]}
          />
          <p className="text-[11px] leading-relaxed text-muted">
            {zhihuFollowMode === "api"
              ? L(
                  locale,
                  "推荐：仅需知乎 Cookie，无需 RSSHub。每轮轮换扫描部分关注用户。",
                  "Recommended: Zhihu cookie only, no RSSHub. Rotates through followees each run."
                )
              : L(
                  locale,
                  "旧模式：需自建 RSSHub 并维护 feeds.yaml。",
                  "Legacy: requires self-hosted RSSHub and feeds.yaml."
                )}
          </p>
        </div>

        {zhihuFollowMode === "api" ? (
          <div className="space-y-2">
            <FieldLabel>{L(locale, "每轮扫描关注人数", "Followees per sync run")}</FieldLabel>
            <input
              type="number"
              min={1}
              max={200}
              className={`${inputClass} w-32`}
              value={zhihuMaxFollowees}
              onChange={(e) => setZhihuMaxFollowees(Math.max(1, Math.min(200, Number(e.target.value) || 25)))}
            />
            <p className="text-[11px] leading-relaxed text-amber-700/90 dark:text-amber-300/90">
              {L(
                locale,
                "数值越大单次拉取越多，但更容易触发知乎限流。建议 10–40；关注很多时会多轮轮换扫完。",
                "Higher values fetch more per run but may trigger Zhihu rate limits. Try 10–40; many followees are covered over multiple runs."
              )}
            </p>
            <FieldLabel>{L(locale, "每位关注者扫描页数", "Pages per followee")}</FieldLabel>
            <input
              type="number"
              min={1}
              max={20}
              className={`${inputClass} w-32`}
              value={zhihuMaxPages}
              onChange={(e) => setZhihuMaxPages(Math.max(1, Math.min(20, Number(e.target.value) || 2)))}
            />
            <FieldLabel>{L(locale, "补扫历史页数", "Backfill pages per followee")}</FieldLabel>
            <input
              type="number"
              min={1}
              max={50}
              className={`${inputClass} w-32`}
              value={zhihuBackfillPages}
              onChange={(e) => setZhihuBackfillPages(Math.max(1, Math.min(50, Number(e.target.value) || 5)))}
            />
            <p className="text-[11px] leading-relaxed text-muted">
              {L(
                locale,
                "执行「初始同步 / 补扫」时每位关注者多翻几页历史动态。",
                "Extra pages per followee during initial sync / backfill runs."
              )}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-2">
              <FieldLabel>{L(locale, "RSSHub 地址", "RSSHub base URL")}</FieldLabel>
              <input
                className={inputClass}
                value={zhihuRsshubBase}
                onChange={(e) => setZhihuRsshubBase(e.target.value)}
                placeholder="http://127.0.0.1:1200"
              />
            </div>
            <ToggleRow
              label={L(locale, "自动刷新关注列表", "Auto-refresh follow list")}
              description={L(
                locale,
                "同步前用 Cookie 更新 feeds.yaml 中的知乎关注 RSS。",
                "Refresh Zhihu follow feeds in feeds.yaml from cookie before sync."
              )}
              checked={zhihuAutoRefreshFollows}
              onChange={setZhihuAutoRefreshFollows}
            />
          </div>
        )}

        <div className="space-y-3 border-t border-border pt-4">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            {L(locale, "B 站订阅", "Bilibili")}
          </h4>
          <FieldLabel>{L(locale, "拉取模式", "Poll mode")}</FieldLabel>
          <SegmentedControl
            value={bilibiliPollMode}
            onChange={(value) => setBilibiliPollMode(value as "dynamic" | "space")}
            options={[
              { value: "dynamic", label: L(locale, "关注动态", "Following feed") },
              { value: "space", label: L(locale, "逐 UP 投稿", "Per-UP space") }
            ]}
          />
          <p className="text-[11px] leading-relaxed text-amber-700/90 dark:text-amber-300/90">
            {bilibiliPollMode === "dynamic"
              ? L(locale, "推荐：关注动态 API，跳过图文/专栏。", "Recommended: following feed API, skips non-video.")
              : L(
                  locale,
                  "逐 UP 扫描空间投稿，关注多时易 412 限流，仅在你明确需要时使用。",
                  "Per-UP space search; easier to hit 412 rate limits with many followees."
                )}
          </p>
          {bilibiliPollMode === "space" ? (
            <div className="space-y-2">
              <FieldLabel>{L(locale, "每轮扫描 UP 数", "UPs per run")}</FieldLabel>
              <input
                type="number"
                min={0}
                max={200}
                className={`${inputClass} w-32`}
                value={bilibiliMaxUps}
                onChange={(e) => setBilibiliMaxUps(Math.max(0, Math.min(200, Number(e.target.value) || 0)))}
              />
              <p className="text-[11px] text-muted">{L(locale, "0 = 不限制，一次扫全部关注。", "0 = no cap, scan all followees in one run.")}</p>
            </div>
          ) : (
            <div className="space-y-2">
              <FieldLabel>{L(locale, "动态列表页数", "Dynamic feed pages")}</FieldLabel>
              <input
                type="number"
                min={1}
                max={50}
                className={`${inputClass} w-32`}
                value={bilibiliDynamicPages}
                onChange={(e) => setBilibiliDynamicPages(Math.max(1, Math.min(50, Number(e.target.value) || 5)))}
              />
              <FieldLabel>{L(locale, "补扫动态页数", "Dynamic backfill pages")}</FieldLabel>
              <input
                type="number"
                min={1}
                max={100}
                className={`${inputClass} w-32`}
                value={bilibiliDynamicBackfillPages}
                onChange={(e) =>
                  setBilibiliDynamicBackfillPages(Math.max(1, Math.min(100, Number(e.target.value) || 20)))
                }
              />
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <FieldLabel>{L(locale, "限流退避（秒）", "Rate-limit backoff (s)")}</FieldLabel>
              <input
                type="number"
                min={5}
                max={600}
                className={inputClass}
                value={bilibiliRateBackoff}
                onChange={(e) => setBilibiliRateBackoff(Math.max(5, Math.min(600, Number(e.target.value) || 45)))}
              />
            </div>
            <div className="space-y-2">
              <FieldLabel>{L(locale, "限流冷却（秒）", "Rate-limit cooldown (s)")}</FieldLabel>
              <input
                type="number"
                min={0}
                max={600}
                className={inputClass}
                value={bilibiliRateCooldown}
                onChange={(e) => setBilibiliRateCooldown(Math.max(0, Math.min(600, Number(e.target.value) || 90)))}
              />
            </div>
          </div>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            {L(locale, "冷启动 / 回填", "Cold start / backfill")}
          </h4>
          <FieldLabel>{L(locale, "每 feed 最多入库条数", "Max items per feed")}</FieldLabel>
          <input
            type="number"
            min={1}
            max={500}
            className={`${inputClass} w-32`}
            value={rssBackfillMaxItems}
            onChange={(e) => setRssBackfillMaxItems(Math.max(1, Math.min(500, Number(e.target.value) || 100)))}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <FieldLabel>{L(locale, "B 站动态回溯天数", "Bilibili dynamic lookback (days)")}</FieldLabel>
              <input
                type="number"
                min={1}
                max={30}
                className={inputClass}
                value={coldStartBiliDays}
                onChange={(e) => setColdStartBiliDays(Math.max(1, Math.min(30, Number(e.target.value) || 3)))}
              />
            </div>
            <div className="space-y-2">
              <FieldLabel>{L(locale, "B 站动态最大页数", "Bilibili dynamic max pages")}</FieldLabel>
              <input
                type="number"
                min={1}
                max={200}
                className={inputClass}
                value={coldStartBiliPages}
                onChange={(e) => setColdStartBiliPages(Math.max(1, Math.min(200, Number(e.target.value) || 50)))}
              />
            </div>
          </div>
        </div>

        <ToggleRow
          label={L(locale, "YouTube 自动刷新频道列表", "Auto-refresh YouTube channels")}
          description={L(
            locale,
            "同步前用 Cookie 自动更新 feeds.yaml 中的 YouTube 频道（国内建议同时配置代理）。",
            "Refresh YouTube channel list from cookie before sync (configure proxy if needed)."
          )}
          checked={youtubeAutoRefresh}
          onChange={setYoutubeAutoRefresh}
        />

        <ToggleRow
          label={L(locale, "后台自动同步", "Background auto sync")}
          description={L(
            locale,
            "On1y 运行时按间隔拉订阅并并行入库/字幕/摘要（与初始同步相同的三路流水线）；首轮通常只 poll。",
            "Poll subscriptions on an interval, then run the same 3-way parallel pipeline as initial sync; first tick is usually poll-only."
          )}
          checked={autoSyncEnabled}
          onChange={setAutoSyncEnabled}
        />
        {autoSyncEnabled ? (
          <div className="space-y-2 pl-1">
            <FieldLabel>{L(locale, "自动同步间隔（分钟）", "Auto sync interval (minutes)")}</FieldLabel>
            <input
              type="number"
              min={5}
              max={1440}
              className={`${inputClass} w-32`}
              value={autoSyncMinutes}
              onChange={(e) => setAutoSyncMinutes(Math.max(5, Math.min(1440, Number(e.target.value) || 30)))}
            />
            <FieldLabel>
              {L(
                locale,
                "并行批次大小（拉取/字幕/摘要）",
                "Parallel batch size (ingest / subtitles / distill)"
              )}
            </FieldLabel>
            <input
              type="number"
              min={5}
              max={100}
              className={`${inputClass} w-32`}
              value={autoSyncBatchSize}
              onChange={(e) =>
                setAutoSyncBatchSize(Math.max(5, Math.min(100, Number(e.target.value) || 25)))
              }
            />
            <p className="text-xs text-neutral-500">
              {L(
                locale,
                "默认 25，与初始同步一致；每轮会排空当前队列（非固定条数上限）。",
                "Default 25, same as initial sync; each run drains pending queues (not a fixed cap)."
              )}
            </p>
          </div>
        ) : null}

        <ToggleRow
          label={L(locale, "后台收藏夹同步", "Background collections sync")}
          description={L(
            locale,
            "自动扫描 B 站 / 知乎 / YouTube 收藏夹中的新链接。",
            "Periodically scan Bilibili / Zhihu / YouTube collections for new URLs."
          )}
          checked={collectionsSyncEnabled}
          onChange={setCollectionsSyncEnabled}
        />
        {collectionsSyncEnabled ? (
          <div className="space-y-2 pl-1">
            <FieldLabel>{L(locale, "收藏夹扫描间隔（秒）", "Collections interval (seconds)")}</FieldLabel>
            <input
              type="number"
              min={30}
              max={3600}
              className={`${inputClass} w-32`}
              value={collectionsSyncSeconds}
              onChange={(e) =>
                setCollectionsSyncSeconds(Math.max(30, Math.min(3600, Number(e.target.value) || 120)))
              }
            />
            <FieldLabel>{L(locale, "收藏夹平台", "Collection platforms")}</FieldLabel>
            <div className="grid gap-2 sm:grid-cols-2">
              {SUB_PLATFORMS.map((platform) => (
                <label
                  key={platform.key}
                  className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs text-foreground"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-accent"
                    checked={collectionsSyncPlatforms.includes(platform.key)}
                    disabled={collectionsSyncPlatforms.length === 1 && collectionsSyncPlatforms.includes(platform.key)}
                    onChange={() =>
                      setCollectionsSyncPlatforms((prev) =>
                        prev.includes(platform.key)
                          ? prev.filter((key) => key !== platform.key)
                          : [...prev, platform.key]
                      )
                    }
                  />
                  {platform.label}
                </label>
              ))}
            </div>
            <p className="text-[11px] leading-relaxed text-muted">
              {L(
                locale,
                "可单独关闭 YouTube 收藏夹扫描；至少保留一个平台。",
                "Disable YouTube collection scanning independently; keep at least one platform selected."
              )}
            </p>
          </div>
        ) : null}
      </section>
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

function BooksTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale, onMessage } = props;
  const [bookCacheDir, setBookCacheDir] = useState("");
  const [folderSyncEnabled, setFolderSyncEnabled] = useState(false);
  const [scanningBookFolder, setScanningBookFolder] = useState(false);
  const [bookFormatFilters, setBookFormatFilters] = useState<BookFormat[]>([]);
  const [bookResolvedCacheDir, setBookResolvedCacheDir] = useState("");
  const [zlibEnabled, setZlibEnabled] = useState(true);
  const [annasEnabled, setAnnasEnabled] = useState(true);
  const [annasSecretKey, setAnnasSecretKey] = useState("");
  const [browsingBookCacheDir, setBrowsingBookCacheDir] = useState(false);
  const [obsidian, setObsidian] = useState<ObsidianSettingsView | null>(null);
  const [obsidianSaving, setObsidianSaving] = useState(false);
  const [obsidianRunning, setObsidianRunning] = useState(false);
  const [browsingObsidianVault, setBrowsingObsidianVault] = useState(false);
  const [browsingObsidianInbox, setBrowsingObsidianInbox] = useState(false);
  const [obsidianStatus, setObsidianStatus] = useState<{
    running: boolean;
    started_at?: string | null;
    finished_at?: string | null;
    last_report?: Record<string, unknown> | null;
    last_error?: string | null;
    user_id?: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [bookSettings, sourcesFile, obsidianSettings, obsidianSyncStatus] =
          await Promise.all([
            fetchBookSettings(),
            fetchBookSources(),
            getObsidianSettings().catch(() => null),
            getObsidianSyncStatus().catch(() => null)
          ]);
        if (cancelled) {
          return;
        }
        setBookCacheDir(bookSettings.cache_dir ?? "");
        setFolderSyncEnabled(Boolean(bookSettings.folder_sync_enabled));
        const filters =
          bookSettings.format_filters && bookSettings.format_filters.length > 0
            ? bookSettings.format_filters
            : bookSettings.format_filter
              ? [bookSettings.format_filter]
              : [];
        setBookFormatFilters(filters);
        setBookResolvedCacheDir(bookSettings.resolved_cache_dir ?? "");
        const toggles = readBuiltinToggles(sourcesFile);
        setZlibEnabled(toggles.zlibEnabled);
        setAnnasEnabled(toggles.annasEnabled);
        setAnnasSecretKey(bookSettings.annas_secret_key ?? "");
        setObsidian(obsidianSettings);
        setObsidianStatus(obsidianSyncStatus);
      } catch (err) {
        onMessageRef.current?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onBrowseBookCacheDir(): Promise<void> {
    setBrowsingBookCacheDir(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      setBookCacheDir(picked);
      const saved = await saveBookSettings({ cache_dir: picked });
      setBookCacheDir(saved.cache_dir ?? picked);
      setBookResolvedCacheDir(saved.resolved_cache_dir ?? "");
      onMessage?.(L(locale, "缓存目录已保存", "Cache folder saved"));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowsingBookCacheDir(false);
    }
  }

  async function scanBookFolderNow(): Promise<void> {
    setScanningBookFolder(true);
    try {
      const result = await scanBookFolder();
      const detail = result.errors.length > 0 ? ` · ${result.errors.join("；")}` : "";
      onMessage?.(
        locale === "zh"
          ? `文件夹扫描完成：新增 ${result.imported} 本${detail}`
          : `Folder scan complete: ${result.imported} new book(s)${detail}`
      );
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setScanningBookFolder(false);
    }
  }
  async function onBrowseObsidianVault(): Promise<void> {
    setBrowsingObsidianVault(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      setObsidian((prev) => (prev ? { ...prev, vault_path: picked } : prev));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowsingObsidianVault(false);
    }
  }

  function normalizeFsPath(input: string): string {
    return input.replace(/\\/g, "/").replace(/\/+$/, "");
  }

  function toVaultRelativePath(vaultPath: string, pickedPath: string): string | null {
    const vaultNorm = normalizeFsPath(vaultPath).toLowerCase();
    const pickedNorm = normalizeFsPath(pickedPath);
    const pickedLower = pickedNorm.toLowerCase();
    if (!vaultNorm || pickedLower === vaultNorm) {
      return "";
    }
    const prefix = `${vaultNorm}/`;
    if (!pickedLower.startsWith(prefix)) {
      return null;
    }
    return pickedNorm.slice(prefix.length).replace(/^\/+/, "");
  }

  async function onBrowseObsidianRelPath(field: "inbox_relpath"): Promise<void> {
    if (!obsidian?.vault_path.trim()) {
      onMessage?.(L(locale, "请先设置 Vault 路径", "Set Vault path first"));
      return;
    }
    setBrowsingObsidianInbox(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      const rel = toVaultRelativePath(obsidian.vault_path, picked);
      if (rel === null) {
        onMessage?.(
          L(
            locale,
            "所选目录不在当前 Vault 下，请在 Vault 内选择目录",
            "Selected folder is outside current vault; choose one inside vault"
          )
        );
        return;
      }
      setObsidian((prev) => (prev ? { ...prev, [field]: rel || "" } : prev));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowsingObsidianInbox(false);
    }
  }

  async function save(): Promise<void> {
    setSaving(true);
    try {
      const [bookSettings] = await Promise.all([
        saveBookSettings({
          cache_dir: bookCacheDir.trim() || null,
          folder_sync_enabled: folderSyncEnabled,
          format_filters: bookFormatFilters,
          format_filter: bookFormatFilters.length === 1 ? bookFormatFilters[0] : null,
          preferred_format: bookFormatFilters[0] ?? "epub",
          annas_secret_key: annasSecretKey.trim() || null
        }),
        saveBookSources(buildBuiltinSourcesSave(zlibEnabled, annasEnabled))
      ]);
      setBookCacheDir(bookSettings.cache_dir ?? "");
      const filters =
        bookSettings.format_filters && bookSettings.format_filters.length > 0
          ? bookSettings.format_filters
          : bookSettings.format_filter
            ? [bookSettings.format_filter]
            : [];
      setBookFormatFilters(filters);
      setBookResolvedCacheDir(bookSettings.resolved_cache_dir ?? "");
      onMessage?.(L(locale, "图书设置已保存", "Book settings saved"));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function saveObsidian(): Promise<void> {
    if (!obsidian) {
      return;
    }
    setObsidianSaving(true);
    try {
      const saved = await saveObsidianSettings(obsidian);
      setObsidian(saved);
      onMessage?.(L(locale, "Obsidian 设置已保存", "Obsidian settings saved"));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setObsidianSaving(false);
    }
  }

  async function runObsidianNow(): Promise<void> {
    setObsidianRunning(true);
    try {
      const report = await runObsidianSync();
      onMessage?.(
        L(
          locale,
          `Obsidian 同步完成：导入 ${report.imported}，跳过 ${report.skipped}，失败 ${report.failed}`,
          `Obsidian sync done: imported ${report.imported}, skipped ${report.skipped}, failed ${report.failed}`
        )
      );
      const status = await getObsidianSyncStatus().catch(() => null);
      if (status) {
        setObsidianStatus(status);
      }
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setObsidianRunning(false);
    }
  }

  if (loading) {
    return <LoadingRow locale={locale} />;
  }

  return (
    <div className="space-y-6">
      <p className="text-xs leading-relaxed text-neutral-500">
        {L(
          locale,
          "下载走 API：先在「订阅」页导入 Z-Library Cookie（remix_userid / remix_userkey）；失败时自动尝试安娜档案。会员可填下方 Secret Key 启用 fast_download。",
          "Downloads use APIs: import Z-Library cookies under Subscriptions first; Anna's Archive is the fallback. Members can add a Secret Key below for fast_download."
        )}
      </p>
      <div>
        <FieldLabel>{L(locale, "电子书缓存目录", "Ebook cache folder")}</FieldLabel>
        <div className="flex gap-2">
          <input
            className={`${inputClass} min-w-0 flex-1`}
            value={bookCacheDir}
            onChange={(e) => setBookCacheDir(e.target.value)}
            placeholder={
              bookResolvedCacheDir || L(locale, "留空使用默认目录", "Leave empty for default folder")
            }
          />
          <button
            type="button"
            className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
            disabled={browsingBookCacheDir || saving}
            onClick={() => void onBrowseBookCacheDir()}
          >
            {browsingBookCacheDir ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FolderOpen className="h-4 w-4" />
            )}
            {L(locale, "浏览…", "Browse…")}
          </button>
        </div>
        {bookResolvedCacheDir ? (
          <p className="mt-1 text-[11px] text-neutral-400">
            {L(locale, "当前生效：", "Active path: ")}
            {bookResolvedCacheDir}
          </p>
        ) : null}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-panel px-3 py-2">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
            <input
              type="checkbox"
              className="rounded border-border"
              checked={folderSyncEnabled}
              disabled={saving}
              onChange={(e) => setFolderSyncEnabled(e.target.checked)}
            />
            {L(locale, "自动同步此文件夹", "Watch this folder automatically")}
          </label>
          <button
            type="button"
            className={`${ghostBtn} px-2 py-1 text-xs`}
            disabled={scanningBookFolder || saving || !folderSyncEnabled}
            onClick={() => void scanBookFolderNow()}
          >
            {scanningBookFolder ? L(locale, "扫描中…", "Scanning…") : L(locale, "立即扫描", "Scan now")}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-muted">
          {L(
            locale,
            "开启后每 15 秒扫描一次该目录。发现 PDF、EPUB、MOBI 会自动加入书库并按 Kindle 设置尝试发送；已处理文件不会重复入库。",
            "When enabled, this folder is scanned every 15 seconds. New PDF, EPUB, and MOBI files are added to the shelf and sent using Kindle settings; processed files are not duplicated."
          )}
        </p>
        <p className="mt-1 text-[11px] text-muted">
          {L(locale, "点「浏览」选目录后会立即保存。", "Picking a folder with Browse saves immediately.")}
        </p>
      </div>
      <div>
        <FieldLabel>{L(locale, "预览格式", "Preview formats")}</FieldLabel>
        <p className="mb-2 text-[11px] text-muted">
          {L(
            locale,
            "勾选后，选书时每种格式各展示最受欢迎的前 3 条（三格全选最多 9 条）。全不勾选则不限格式，共 3 条。",
            "Checked formats each show top 3 by popularity (up to 9 if all three). None checked = any format, 3 total."
          )}
        </p>
        <div className="flex flex-wrap gap-4">
          {BOOK_FORMATS.map((fmt) => {
            const checked = bookFormatFilters.includes(fmt);
            return (
              <label key={fmt} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={checked}
                  onChange={() => {
                    setBookFormatFilters((prev) =>
                      checked ? prev.filter((f) => f !== fmt) : [...prev, fmt]
                    );
                  }}
                />
                <span>{fmt.toUpperCase()}</span>
              </label>
            );
          })}
        </div>
      </div>
      <div className="space-y-2 border-t border-border pt-4">
        <FieldLabel>{L(locale, "书库来源", "Sources")}</FieldLabel>
        <ToggleRow
          label="Z-Library"
          description={L(
            locale,
            "zh.z-lib.help · 与安娜档案 API 下载",
            "zh.z-lib.help · API download with Anna's Archive fallback"
          )}
          checked={zlibEnabled}
          onChange={setZlibEnabled}
        />
        <ToggleRow
          label={L(locale, "安娜档案", "Anna's Archive")}
          description={L(
            locale,
            "annas-archive.gl · 搜索结果与详情页外链",
            "annas-archive.gl · link in search results and book detail"
          )}
          checked={annasEnabled}
          onChange={setAnnasEnabled}
        />
        <p className="text-[11px] text-muted">
          {L(locale, "豆瓣搜索始终开启。", "Douban search is always on.")}
        </p>
      </div>
      <div>
        <FieldLabel>{L(locale, "安娜档案 Secret Key", "Anna's Archive Secret Key")}</FieldLabel>
        <input
          className={inputClass}
          type="password"
          value={annasSecretKey}
          onChange={(e) => setAnnasSecretKey(e.target.value)}
          placeholder={L(locale, "可选，会员 fast_download", "Optional, for member fast_download")}
          autoComplete="off"
        />
        <p className="mt-1 text-[11px] text-muted">
          {L(
            locale,
            "在 tw.annas-archive.gl/account/secret_key 获取；留空则尝试免费镜像链接。",
            "From tw.annas-archive.gl/account/secret_key; leave empty to try free mirror links."
          )}
        </p>
      </div>
      <div className="space-y-3 border-t border-border pt-4">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-muted" />
          <FieldLabel>{L(locale, "Obsidian 同步", "Obsidian sync")}</FieldLabel>
        </div>
        <p className="text-[11px] text-muted">
          {L(
            locale,
            "将 Obsidian 中指定目录的 Markdown 导入 On1y（默认每 60 秒）。",
            "Import Markdown from a configured Obsidian folder into On1y (default every 60 seconds)."
          )}
        </p>
        {obsidian ? (
          <div className="space-y-2 rounded-lg border border-border bg-panel/60 px-3 py-3">
            <ToggleRow
              label={L(locale, "启用 Obsidian 自动导入", "Enable Obsidian auto-import")}
              checked={obsidian.enabled}
              onChange={(checked) => setObsidian((prev) => (prev ? { ...prev, enabled: checked } : prev))}
            />
            <ToggleRow
              label={L(locale, "启用 On1y 写回 Obsidian", "Enable On1y writeback to Obsidian")}
              checked={obsidian.writeback_enabled}
              onChange={(checked) =>
                setObsidian((prev) => (prev ? { ...prev, writeback_enabled: checked } : prev))
              }
            />
            <div>
              <FieldLabel>{L(locale, "Vault 路径", "Vault path")}</FieldLabel>
              <div className="flex gap-2">
                <input
                  className={`${inputClass} min-w-0 flex-1`}
                  value={obsidian.vault_path}
                  onChange={(e) =>
                    setObsidian((prev) => (prev ? { ...prev, vault_path: e.target.value } : prev))
                  }
                  placeholder="D:\\ObsidianVault"
                />
                <button
                  type="button"
                  className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
                  disabled={browsingObsidianVault}
                  onClick={() => void onBrowseObsidianVault()}
                  title={L(locale, "浏览本地目录", "Browse local folder")}
                >
                  {browsingObsidianVault ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FolderOpen className="h-4 w-4" />
                  )}
                  {L(locale, "浏览", "Browse")}
                </button>
              </div>
            </div>
            <div>
              <FieldLabel>{L(locale, "导入目录（相对路径）", "Import folder (relative path)")}</FieldLabel>
              <div className="flex gap-2">
                <input
                  className={`${inputClass} min-w-0 flex-1`}
                  value={obsidian.inbox_relpath}
                  onChange={(e) =>
                    setObsidian((prev) => (prev ? { ...prev, inbox_relpath: e.target.value } : prev))
                  }
                  placeholder="Inbox/Clippings"
                />
                <button
                  type="button"
                  className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
                  disabled={browsingObsidianInbox}
                  onClick={() => void onBrowseObsidianRelPath("inbox_relpath")}
                  title={L(locale, "浏览 Vault 内目录", "Browse folder in vault")}
                >
                  {browsingObsidianInbox ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FolderOpen className="h-4 w-4" />
                  )}
                  {L(locale, "浏览", "Browse")}
                </button>
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <div>
                <FieldLabel>{L(locale, "扫描周期（秒）", "Interval (seconds)")}</FieldLabel>
                <input
                  type="number"
                  min={15}
                  max={3600}
                  className={inputClass}
                  value={obsidian.interval_seconds}
                  onChange={(e) =>
                    setObsidian((prev) =>
                      prev
                        ? { ...prev, interval_seconds: Math.max(15, Math.min(3600, Number(e.target.value) || 60)) }
                        : prev
                    )
                  }
                />
              </div>
              <div className="pt-5">
                <label className="inline-flex items-center gap-2 text-xs text-muted">
                  <input
                    type="checkbox"
                    className="rounded border-border"
                    checked={obsidian.auto_distill}
                    onChange={(e) =>
                      setObsidian((prev) => (prev ? { ...prev, auto_distill: e.target.checked } : prev))
                    }
                  />
                  {L(locale, "自动摘要", "Auto distill")}
                </label>
              </div>
            </div>
            <p className="text-[11px] text-muted">
              {L(
                locale,
                "Obsidian 与 On1y 独立管理：导入只读，不会移动或删除你的 Vault 文件。",
                "Obsidian and On1y are independent: import is read-only and never moves/deletes vault files."
              )}
            </p>
            {obsidianStatus?.last_error ? (
              <p className="text-xs text-red-500">{obsidianStatus.last_error}</p>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className={ghostBtn}
                disabled={obsidianRunning}
                onClick={() => void runObsidianNow()}
              >
                {obsidianRunning ? L(locale, "同步中…", "Syncing…") : L(locale, "立即同步", "Run sync now")}
              </button>
              <button type="button" className={primaryBtn} disabled={obsidianSaving} onClick={() => void saveObsidian()}>
                {obsidianSaving ? L(locale, "保存中…", "Saving…") : L(locale, "保存 Obsidian 设置", "Save Obsidian settings")}
              </button>
            </div>
          </div>
        ) : (
          <LoadingRow locale={locale} />
        )}
      </div>
      <div className="flex justify-end">
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
      </div>
    </div>
  );
}

function PapersTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale, onMessage } = props;
  const [settings, setSettings] = useState<PaperSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [browsingApplication, setBrowsingApplication] = useState(false);
  const [running, setRunning] = useState<"folder" | "zotero" | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let cancelled = false;
    void fetchPaperSettings()
      .then((value) => {
        if (!cancelled) setSettings(value);
      })
      .catch((error) => onMessageRef.current?.(error instanceof Error ? error.message : String(error)))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function patch(value: Partial<PaperSettings>): void {
    setSettings((current) => (current ? { ...current, ...value } : current));
  }

  async function browse(): Promise<void> {
    setBrowsing(true);
    try {
      const picked = await pickFolder();
      if (picked) patch({ cache_dir: picked });
    } catch (error) {
      onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setBrowsing(false);
    }
  }

  async function browsePdfApplication(): Promise<void> {
    setBrowsingApplication(true);
    try {
      const picked = await pickPdfApplication();
      if (picked) patch({ pdf_application_path: picked });
    } catch (error) {
      onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setBrowsingApplication(false);
    }
  }

  async function save(): Promise<PaperSettings | null> {
    if (!settings) return null;
    setSaving(true);
    try {
      const saved = await savePaperSettings(settings);
      setSettings(saved);
      onMessage?.(L(locale, "Paper 设置已保存", "Paper settings saved"));
      return saved;
    } catch (error) {
      onMessage?.(error instanceof Error ? error.message : String(error));
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function run(kind: "folder" | "zotero"): Promise<void> {
    if (!settings) return;
    setRunning(kind);
    try {
      const saved = await savePaperSettings(settings);
      setSettings(saved);
      const result = kind === "folder" ? await scanPaperFolder() : await syncZoteroPapers();
      if (!result.enabled) {
        onMessage?.(L(locale, "请先启用对应的同步开关", "Enable this sync first"));
        return;
      }
      const errorText = result.errors.length ? ` · ${result.errors[0]}` : "";
      onMessage?.(
        L(
          locale,
          `同步完成：新增 ${result.imported} 篇，更新 ${result.updated ?? 0} 篇，跳过 ${result.skipped ?? 0} 篇${errorText}`,
          `Sync complete: ${result.imported} imported, ${result.updated ?? 0} updated, ${result.skipped ?? 0} skipped${errorText}`
        )
      );
    } catch (error) {
      onMessage?.(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(null);
    }
  }

  if (loading || !settings) return <LoadingRow locale={locale} />;

  return (
    <div className="space-y-7">
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{L(locale, "PDF 打开方式", "PDF reader")}</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {L(locale, "选择 Paper 中 PDF 的默认阅读应用。", "Choose how PDFs are opened from Papers.")}
          </p>
        </div>
        <SegmentedControl
          value={settings.pdf_open_mode}
          options={[
            { value: "zotero", label: "Zotero" },
            { value: "system", label: L(locale, "系统默认", "System default") },
            { value: "custom", label: L(locale, "指定应用", "Custom app") }
          ]}
          onChange={(value) => patch({ pdf_open_mode: value })}
        />
        {settings.pdf_open_mode === "custom" ? (
          <label className="block">
            <FieldLabel>{L(locale, "PDF 阅读应用", "PDF application")}</FieldLabel>
            <div className="flex gap-2">
              <input
                className={`${inputClass} min-w-0 flex-1`}
                value={settings.pdf_application_path ?? ""}
                readOnly
                placeholder={L(locale, "请选择应用程序（.exe）", "Choose an application (.exe)")}
              />
              <button
                type="button"
                className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn}`}
                disabled={browsingApplication || !isDesktopShell()}
                onClick={() => void browsePdfApplication()}
              >
                {browsingApplication ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
                {L(locale, "选择应用…", "Choose app…")}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-muted">
              {L(locale, "应用选择仅在桌面版可用；若应用失效，会回退到系统默认阅读器。", "Application selection is available in the desktop app. If it fails, the system reader is used.")}
            </p>
          </label>
        ) : (
          <p className="text-xs text-muted">
            {settings.pdf_open_mode === "zotero"
              ? L(locale, "优先使用 Zotero 阅读器；没有 Zotero 附件时使用本地 PDF。", "Prefer Zotero Reader, falling back to the local PDF when needed.")
              : L(locale, "使用 Windows 当前为 PDF 配置的默认应用。", "Use the current Windows default application for PDFs.")}
          </p>
        )}
      </section>

      <section className="space-y-4 border-t border-border pt-6">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{L(locale, "本地 PDF", "Local PDFs")}</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {L(locale, "监控指定目录，把新增 PDF 自动加入 Paper。", "Watch a folder and add new PDFs to Papers automatically.")}
          </p>
        </div>
        <label className="block">
          <FieldLabel>{L(locale, "Paper 文件夹", "Paper folder")}</FieldLabel>
          <div className="flex gap-2">
            <input
              className={`${inputClass} min-w-0 flex-1`}
              value={settings.cache_dir ?? ""}
              onChange={(event) => patch({ cache_dir: event.target.value })}
              placeholder={settings.resolved_cache_dir || L(locale, "使用默认目录", "Use default folder")}
            />
            <button type="button" className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn}`} disabled={browsing} onClick={() => void browse()}>
              {browsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
              {L(locale, "选择…", "Choose…")}
            </button>
          </div>
          {settings.resolved_cache_dir ? (
            <p className="mt-1.5 break-all text-[11px] text-muted">{settings.resolved_cache_dir}</p>
          ) : null}
        </label>
        <ToggleRow
          label={L(locale, "启用文件夹同步", "Enable folder sync")}
          description={L(locale, "后台定期扫描此目录；已存在的论文会被识别并跳过或合并。", "Scan this folder in the background; existing papers are skipped or merged.")}
          checked={settings.folder_sync_enabled}
          onChange={(checked) => patch({ folder_sync_enabled: checked })}
        />
        <div className="flex justify-end">
          <button type="button" className={ghostBtn} disabled={running !== null} onClick={() => void run("folder")}>
            {running === "folder" ? L(locale, "扫描中…", "Scanning…") : L(locale, "保存并立即扫描", "Save and scan now")}
          </button>
        </div>
      </section>

      <section className="space-y-4 border-t border-border pt-6">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Zotero</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {L(locale, "连接 Zotero Desktop 本地 API，或使用 Zotero Web API。", "Connect to the Zotero Desktop local API or Zotero Web API.")}
          </p>
        </div>
        <ToggleRow
          label={L(locale, "启用 Zotero 同步", "Enable Zotero sync")}
          description={L(locale, "同步论文元数据，并可下载 PDF 附件。", "Sync paper metadata and optionally download PDF attachments.")}
          checked={settings.zotero_enabled}
          onChange={(checked) => patch({ zotero_enabled: checked })}
        />
        <div>
          <FieldLabel>{L(locale, "连接方式", "Connection")}</FieldLabel>
          <SegmentedControl
            value={settings.zotero_mode}
            options={[
              { value: "local", label: "Zotero Desktop" },
              { value: "web", label: "Zotero Web" }
            ]}
            onChange={(value) => patch({
              zotero_mode: value,
              zotero_base_url: value === "local" ? "http://localhost:23119/api" : "https://api.zotero.org"
            })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <FieldLabel>{L(locale, "文库类型", "Library type")}</FieldLabel>
            <select
              className={inputClass}
              value={settings.zotero_library_type}
              onChange={(event) => patch({ zotero_library_type: event.target.value as "users" | "groups" })}
            >
              <option value="users">{L(locale, "个人文库", "User library")}</option>
              <option value="groups">{L(locale, "群组文库", "Group library")}</option>
            </select>
          </label>
          <label>
            <FieldLabel>Library ID</FieldLabel>
            <input className={inputClass} value={settings.zotero_library_id} onChange={(event) => patch({ zotero_library_id: event.target.value })} />
          </label>
        </div>
        <label className="block">
          <FieldLabel>API URL</FieldLabel>
          <input className={inputClass} value={settings.zotero_base_url} onChange={(event) => patch({ zotero_base_url: event.target.value })} />
        </label>
        <label className="block">
          <FieldLabel>API Key {L(locale, "（Web 模式）", "(Web mode)")}</FieldLabel>
          <input type="password" className={inputClass} value={settings.zotero_api_key ?? ""} onChange={(event) => patch({ zotero_api_key: event.target.value })} />
        </label>
        <label className="block">
          <FieldLabel>Collection Key {L(locale, "（可选）", "(optional)")}</FieldLabel>
          <input className={inputClass} value={settings.zotero_collection_key ?? ""} onChange={(event) => patch({ zotero_collection_key: event.target.value })} />
        </label>
        <ToggleRow
          label={L(locale, "同步 PDF 附件", "Sync PDF attachments")}
          description={L(locale, "优先复用已经存在的本地 PDF，不会再次生成同名副本。", "Reuse an existing local PDF instead of creating another copy.")}
          checked={settings.zotero_download_pdfs}
          onChange={(checked) => patch({ zotero_download_pdfs: checked })}
        />
        <div className="flex justify-end">
          <button type="button" className={ghostBtn} disabled={running !== null} onClick={() => void run("zotero")}>
            {running === "zotero" ? L(locale, "同步中…", "Syncing…") : L(locale, "保存并立即同步", "Save and sync now")}
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-xs leading-relaxed text-emerald-900">
        <p className="font-medium">{L(locale, "双重同步不会创建两篇相同 Paper", "Folder + Zotero sync will not create duplicate papers")}</p>
        <p className="mt-1 text-emerald-800/80">
          {L(locale, "系统依次按 Zotero ID、DOI、PDF 路径、标题与年份/作者识别同一论文。匹配后只合并来源信息，并保留你的阅读状态、笔记、星级、主题和本地标签。", "Papers are matched by Zotero ID, DOI, PDF path, then title with year/author checks. Source metadata is merged while your reading status, notes, rating, theme, and local tags are preserved.")}
        </p>
      </section>

      <div className="flex justify-end border-t border-border pt-5">
        <button type="button" className={primaryBtn} disabled={saving || running !== null} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存 Paper 设置", "Save Paper settings")}
        </button>
      </div>
    </div>
  );
}

function PushTab(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const { locale } = props;
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [smtpView, setSmtpView] = useState<SmtpSettingsView | null>(null);
  const [kindleTo, setKindleTo] = useState("");
  const [autoIngest, setAutoIngest] = useState(false);
  const [autoKindle, setAutoKindle] = useState(false);
  const [economistAutoSync, setEconomistAutoSync] = useState(true);
  const [economistSyncMinutes, setEconomistSyncMinutes] = useState(60);
  const [economistGithubMirror, setEconomistGithubMirror] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpFrom, setSmtpFrom] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  function applySmtpView(data: SmtpSettingsView): void {
    setSmtpView(data);
    setSmtpHost(data.host);
    setSmtpPort(data.port);
    setSmtpUser(data.user);
    setSmtpFrom(data.from || data.user);
    setSmtpUseTls(data.use_tls);
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [data, smtp, syncSettings] = await Promise.all([
          getUserProfile(),
          getSmtpSettings(),
          getSyncSettings()
        ]);
        if (cancelled) {
          return;
        }
        setProfile(data);
        setKindleTo(data.kindle.send_to);
        setAutoIngest(data.economist.auto_ingest_enabled);
        setAutoKindle(data.economist.auto_kindle_enabled);
        setEconomistAutoSync(Boolean(syncSettings.economist_auto_sync_enabled));
        setEconomistSyncMinutes(syncSettings.economist_auto_sync_interval_minutes);
        setEconomistGithubMirror(syncSettings.economist_github_raw_base ?? "");
        applySmtpView(smtp);
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

  function smtpPayload() {
    const user = smtpUser.trim();
    return {
      host: smtpHost.trim(),
      port: smtpPort,
      user,
      from_addr: smtpFrom.trim() || user,
      password: smtpPassword.trim() || undefined,
      use_tls: smtpUseTls
    };
  }

  async function save(): Promise<void> {
    setSaving(true);
    try {
      const [data, smtp] = await Promise.all([
        patchUserProfile({
          kindle_send_to: kindleTo.trim(),
          kindle_enabled: Boolean(kindleTo.trim()),
          economist_auto_ingest: autoIngest,
          economist_auto_kindle: autoKindle
        }),
        saveSmtpSettings(smtpPayload()),
        saveSyncSettings({
          economist_auto_sync_enabled: economistAutoSync,
          economist_auto_sync_interval_minutes: economistSyncMinutes,
          economist_github_raw_base: economistGithubMirror.trim()
        })
      ]);
      setProfile(data);
      applySmtpView(smtp);
      setSmtpPassword("");
      props.onMessage?.(L(locale, "推送设置已保存", "Delivery settings saved"));
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
      const result = await testSmtpSettings(smtpPayload());
      setTestResult({
        ok: result.ok,
        text: result.ok
          ? `${result.host ?? smtpHost} · ${result.from ?? smtpFrom}`
          : result.error ?? "failed"
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

  const smtpReady = smtpView?.configured ?? false;

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <p className="text-xs leading-relaxed text-neutral-500">
          {L(
            locale,
            "经济学人新刊可自动入库并推送到 Kindle。图书缓存后发送 Kindle 需在此配置邮箱与 SMTP。收件地址在 Amazon「发送至 Kindle」中查看。",
            "Economist editions can auto-ingest and email to Kindle. Book caching also uses the Kindle email and SMTP below. Find your @kindle.com address in Amazon Send to Kindle settings."
          )}
        </p>

        <div>
          <FieldLabel>{L(locale, "Kindle 接收邮箱", "Kindle email")}</FieldLabel>
          <input className={inputClass} value={kindleTo} onChange={(e) => setKindleTo(e.target.value)} placeholder="xxx@kindle.com" />
        </div>

        <ToggleRow
          label={L(locale, "后台检查经济学人新刊", "Background Economist check")}
          description={L(
            locale,
            "On1y 运行时按间隔检查 GitHub 是否有新周刊（需同时开启下方入库）。",
            "Poll GitHub for new editions while On1y runs (requires auto-ingest below)."
          )}
          checked={economistAutoSync}
          onChange={setEconomistAutoSync}
        />
        {economistAutoSync ? (
          <div className="space-y-2 pl-1">
            <FieldLabel>{L(locale, "检查间隔（分钟）", "Check interval (minutes)")}</FieldLabel>
            <input
              type="number"
              min={15}
              max={1440}
              className={`${inputClass} w-32`}
              value={economistSyncMinutes}
              onChange={(e) => setEconomistSyncMinutes(Math.max(15, Math.min(1440, Number(e.target.value) || 60)))}
            />
          </div>
        ) : null}
        <div className="space-y-2">
          <FieldLabel>{L(locale, "GitHub 资源镜像（可选）", "GitHub raw mirror (optional)")}</FieldLabel>
          <input
            className={inputClass}
            value={economistGithubMirror}
            onChange={(e) => setEconomistGithubMirror(e.target.value)}
            placeholder="https://ghfast.top/https://raw.githubusercontent.com/..."
          />
          <p className="text-[11px] text-muted">
            {L(
              locale,
              "国内下载 EPUB 慢时可填镜像前缀；留空用官方 raw.githubusercontent.com。",
              "Prefix mirror when raw.githubusercontent.com is slow; leave empty for official CDN."
            )}
          </p>
        </div>
        <ToggleRow
          label={L(locale, "自动入库经济学人新刊", "Auto-ingest new Economist editions")}
          description={L(locale, "发现新刊后下载并写入知识库。", "Download and store new editions in your library.")}
          checked={autoIngest}
          onChange={setAutoIngest}
        />
        <ToggleRow
          label={L(locale, "新刊自动推送到 Kindle", "Auto-send new editions to Kindle")}
          description={L(locale, "入库成功后邮件发送 EPUB（需配置下方 SMTP）。", "Email EPUB after ingest (configure SMTP below).")}
          checked={autoKindle}
          onChange={setAutoKindle}
        />
      </section>

      <section className="space-y-4 border-t border-border pt-6">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {L(locale, "发件邮箱 (SMTP)", "Outgoing mail (SMTP)")}
        </h3>
        <p className="text-xs leading-relaxed text-neutral-500">
          {L(
            locale,
            "用你自己的 Gmail 等邮箱发送。Gmail 需开启两步验证后生成「应用专用密码」（16 位），不是登录密码。发件地址还须在 Amazon「已认可发件人」列表中。",
            "Send from your own Gmail or SMTP account. Gmail requires 2-Step Verification and a 16-character App Password (not your login password). The sender must also be on Amazon's approved list."
          )}
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <FieldLabel>{L(locale, "SMTP 服务器", "SMTP host")}</FieldLabel>
            <input
              className={inputClass}
              value={smtpHost}
              onChange={(e) => setSmtpHost(e.target.value)}
              placeholder={smtpView?.defaults.host ?? "smtp.gmail.com"}
            />
          </div>
          <div>
            <FieldLabel>{L(locale, "端口", "Port")}</FieldLabel>
            <input
              type="number"
              min={1}
              max={65535}
              className={inputClass}
              value={smtpPort}
              onChange={(e) => setSmtpPort(Math.max(1, Math.min(65535, Number(e.target.value) || 587)))}
            />
          </div>
        </div>

        <div>
          <FieldLabel>{L(locale, "邮箱账号", "Email account")}</FieldLabel>
          <input
            className={inputClass}
            value={smtpUser}
            onChange={(e) => setSmtpUser(e.target.value)}
            placeholder="you@gmail.com"
            autoComplete="username"
          />
        </div>

        <div>
          <FieldLabel>{L(locale, "应用专用密码", "App password")}</FieldLabel>
          <input
            className={inputClass}
            type="password"
            value={smtpPassword}
            onChange={(e) => setSmtpPassword(e.target.value)}
            placeholder={
              smtpView?.password_set
                ? L(locale, "已设置，留空保留", "Set — leave blank to keep")
                : L(locale, "Gmail 16 位应用专用密码", "Gmail 16-char app password")
            }
            autoComplete="new-password"
          />
        </div>

        <div>
          <FieldLabel>{L(locale, "发件人地址", "From address")}</FieldLabel>
          <input
            className={inputClass}
            value={smtpFrom}
            onChange={(e) => setSmtpFrom(e.target.value)}
            placeholder={smtpUser || "you@gmail.com"}
          />
          <p className="mt-1 text-[11px] text-neutral-400">
            {L(
              locale,
              "须与 Amazon 账户里批准的邮箱一致，通常与上方账号相同。",
              "Must match an email approved in your Amazon account; usually the same as the account above."
            )}
          </p>
        </div>

        <ToggleRow
          label={L(locale, "STARTTLS (587)", "STARTTLS (587)")}
          description={L(locale, "Gmail 等常用；关闭则尝试 SSL 直连。", "Typical for Gmail; turn off for direct SSL.")}
          checked={smtpUseTls}
          onChange={setSmtpUseTls}
        />

        <div
          className={`rounded-lg px-3 py-2 text-xs ${smtpReady ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}
        >
          {smtpReady
            ? L(locale, `SMTP 已就绪 · 发件 ${smtpFrom || smtpUser}`, `SMTP ready · from ${smtpFrom || smtpUser}`)
            : L(locale, "SMTP 未配置完整，无法发送到 Kindle", "SMTP incomplete — cannot send to Kindle")}
        </div>

        {testResult ? (
          <div className={`rounded-lg px-3 py-2 text-xs ${testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            {testResult.ok ? L(locale, "连接成功 · ", "Connected · ") : L(locale, "连接失败 · ", "Failed · ")}
            {testResult.text}
          </div>
        ) : null}
      </section>

      <div className="flex justify-end gap-2">
        <button type="button" className={ghostBtn} disabled={testing || saving} onClick={() => void test()}>
          {testing ? L(locale, "测试中…", "Testing…") : L(locale, "测试 SMTP", "Test SMTP")}
        </button>
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

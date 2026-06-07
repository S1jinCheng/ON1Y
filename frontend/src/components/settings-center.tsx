"use client";

import {
  Bot,
  ClipboardPaste,
  Cookie,
  Download,
  FolderOpen,
  Info,
  KeyRound,
  Loader2,
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
  getDesktopAppStatus,
  getLlmSettings,
  getNetworkSettings,
  getSubscriptionSettings,
  getSubscriptionSyncStatus,
  getUserProfile,
  importCookieFromClipboard,
  importUserArchive,
  logout,
  patchDesktopPrefs,
  patchUserProfile,
  runSubscriptionSync,
  saveLlmSettings,
  saveNetworkSettings,
  saveSubscriptionSettings,
  setAutostart,
  testNetworkProxy,
  switchAccount,
  testLlmSettings,
  updateAuthProfile,
  uploadCookieFile,
  type AuthUser,
  type CookiePlatform,
  type CookieStatus,
  type DesktopAppStatus,
  type LlmSettingsView,
  type NetworkSettingsView,
  type UserProfile
} from "@/lib/api";
import { getRecentAuthUsernames } from "@/lib/auth";
import { notifyAppearanceChange } from "@/components/appearance-provider";
import { InitialSyncSection } from "@/components/initial-sync-section";
import { type AppearanceMode, persistStoredAppearance } from "@/lib/appearance";
import type { Locale } from "@/lib/i18n";
import {
  consumeRequestedSettingsTab,
  showFirstRunGuide,
  type SettingsTabKey
} from "@/lib/open-settings";
import { persistStoredLocale } from "@/lib/locale-preference";
import { isDesktopShell, pickDataFolder } from "@/lib/pick-data-folder";
import { saveArchiveFile, triggerBrowserFileDownload } from "@/lib/save-archive-file";

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
    { key: "general", label: L(locale, "通用", "General"), icon: <SlidersHorizontal className="h-4 w-4" /> },
    { key: "account", label: L(locale, "账号", "Account"), icon: <UserCircle2 className="h-4 w-4" /> },
    {
      key: "subscriptions",
      label: L(locale, "订阅与 Cookie", "Subscriptions & cookies"),
      icon: <Cookie className="h-4 w-4" />
    },
    { key: "ai", label: L(locale, "AI", "AI"), icon: <Bot className="h-4 w-4" /> },
    { key: "push", label: L(locale, "推送", "Delivery"), icon: <KeyRound className="h-4 w-4" /> },
    { key: "about", label: L(locale, "关于", "About"), icon: <Info className="h-4 w-4" /> }
  ];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[var(--on1y-overlay)] p-4">
      <div className="flex h-[600px] max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
        <aside className="flex w-48 shrink-0 flex-col border-r border-border bg-panel/80 p-3">
          <div className="px-2 py-2 text-sm font-semibold tracking-tight text-foreground">
            {L(locale, "设置", "Settings")}
          </div>
          <nav className="mt-1 space-y-0.5">
            {tabs.map((item) => (
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
            {tab === "subscriptions" ? (
              <SubscriptionsTab locale={locale} onClose={onClose} onMessage={props.onMessage} />
            ) : null}
            {tab === "ai" ? <AiTab locale={locale} onMessage={props.onMessage} /> : null}
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
  const [archiveExporting, setArchiveExporting] = useState(false);
  const [archiveImporting, setArchiveImporting] = useState(false);
  const [archiveExportIncludeSettings, setArchiveExportIncludeSettings] = useState(false);
  const [archiveExportIncludeTrash, setArchiveExportIncludeTrash] = useState(false);
  const [archiveConflict, setArchiveConflict] = useState<"skip" | "overwrite">("overwrite");
  const [proxyMode, setProxyMode] = useState<"auto" | "manual" | "off">("auto");
  const [manualProxy, setManualProxy] = useState("");
  const [networkStatus, setNetworkStatus] = useState<NetworkSettingsView | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);
  const archiveImportRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [profile, status, network] = await Promise.all([
          getUserProfile(),
          getDesktopAppStatus(),
          getNetworkSettings()
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

  async function onExportArchive(): Promise<void> {
    const exportOptions = {
      includeTrash: archiveExportIncludeTrash,
      includeSettings: archiveExportIncludeSettings
    };
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "").slice(0, 15);
    const filename = `on1y-library-${stamp}.on1y.zip`;

    if (!isDesktopShell()) {
      triggerBrowserFileDownload(buildUserArchiveExportUrl(exportOptions), filename);
      props.onMessage?.(
        L(locale, "正在下载导出文件…", "Downloading export…")
      );
      return;
    }

    setArchiveExporting(true);
    props.onMessage?.(
      L(locale, "正在打包知识库，请稍候…", "Packaging library, please wait…")
    );
    try {
      const blob = await exportUserArchive(exportOptions);
      const savedPath = await saveArchiveFile(filename, new Uint8Array(await blob.arrayBuffer()));
      if (!savedPath) {
        props.onMessage?.(L(locale, "已取消保存", "Save cancelled"));
        return;
      }
      props.onMessage?.(
        L(locale, `知识库已保存到 ${savedPath}`, `Library saved to ${savedPath}`)
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setArchiveExporting(false);
    }
  }

  async function onArchiveFileSelected(file: File | null): Promise<void> {
    if (!file) {
      return;
    }
    setArchiveImporting(true);
    try {
      const result = await importUserArchive(file, archiveConflict);
      let summary = L(
        locale,
        `已导入 ${result.imported} 条，跳过 ${result.skipped} 条，新建主题 ${result.themes_created} 个`,
        `Imported ${result.imported}, skipped ${result.skipped}, ${result.themes_created} themes created`
      );
      if (result.subscription_restored > 0 || result.cookies_restored > 0) {
        summary += L(
          locale,
          `；订阅设置 ${result.subscription_restored > 0 ? "已还原" : "未包含"}，Cookie ${result.cookies_restored} 个`,
          `; subscription ${result.subscription_restored > 0 ? "restored" : "not included"}, ${result.cookies_restored} cookie file(s)`
        );
      }
      if (result.error_count > 0) {
        props.onMessage?.(
          `${summary}；${L(locale, "部分失败", "some errors")}: ${result.errors.slice(0, 3).join("; ")}`
        );
      } else {
        props.onMessage?.(summary);
      }
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setArchiveImporting(false);
      if (archiveImportRef.current) {
        archiveImportRef.current.value = "";
      }
    }
  }

  async function onBrowseDataDir(): Promise<void> {
    setBrowsingDataDir(true);
    try {
      const picked = await pickDataFolder();
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
          {desktop?.is_desktop_shell || isDesktopShell() ? (
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
          ) : null}
        </div>
        <p className="text-[11px] leading-relaxed text-neutral-500">
          {L(
            locale,
            "知识库、Cookie、订阅与 LLM 配置均保存在此目录（按用户分子目录）。桌面版可点「浏览」选择文件夹；修改后需重启。",
            "Knowledge base, cookies, subscriptions, and LLM settings live here (per-user subfolders). Use Browse on desktop; restart after changing."
          )}
        </p>
        <div className="rounded-lg border border-border bg-soft/40 px-3 py-3">
          <p className="text-sm font-medium text-foreground">
            {L(locale, "知识库备份与迁移", "Library backup & migration")}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {L(
              locale,
              "导出当前账号的订阅内容（正文、摘要、标签、主题，不含热榜）。在另一台电脑或另一账号中导入即可快速还原。",
              "Export this account's feed items (body, summaries, tags, themes; hotlist excluded). Import on another machine or account to restore quickly."
            )}
          </p>
          <div className="mt-3 space-y-2">
            <ToggleRow
              label={L(locale, "同时导出 Cookie 与订阅设置", "Include cookies & subscription settings")}
              description={L(
                locale,
                "包含各平台登录 Cookie 与 B 站/YouTube/知乎订阅起始日期。导入时会一并还原。",
                "Includes platform login cookies and Bilibili/YouTube/Zhihu sync-since dates. Restored on import."
              )}
              checked={archiveExportIncludeSettings}
              disabled={archiveExporting || archiveImporting}
              onChange={setArchiveExportIncludeSettings}
            />
            <ToggleRow
              label={L(locale, "包含已删除条目", "Include deleted items")}
              description={L(
                locale,
                "默认只导出回收站以外的内容。",
                "By default only non-trashed items are exported."
              )}
              checked={archiveExportIncludeTrash}
              disabled={archiveExporting || archiveImporting}
              onChange={setArchiveExportIncludeTrash}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
              disabled={archiveExporting || archiveImporting}
              onClick={() => void onExportArchive()}
            >
              {archiveExporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {L(locale, "导出知识库", "Export library")}
            </button>
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
              disabled={archiveExporting || archiveImporting}
              onClick={() => archiveImportRef.current?.click()}
            >
              {archiveImporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {L(locale, "导入知识库", "Import library")}
            </button>
            <input
              ref={archiveImportRef}
              type="file"
              accept=".zip,.on1y.zip,application/zip"
              className="hidden"
              onChange={(e) => void onArchiveFileSelected(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="mt-3">
            <FieldLabel>{L(locale, "导入冲突", "Import conflicts")}</FieldLabel>
            <SegmentedControl
              value={archiveConflict}
              onChange={setArchiveConflict}
              options={[
                { value: "overwrite", label: L(locale, "覆盖", "Overwrite") },
                { value: "skip", label: L(locale, "跳过", "Skip") }
              ]}
            />
            <p className="mt-1 text-[11px] text-muted">
              {L(
                locale,
                "相同 URL 已存在时：覆盖会更新正文与摘要；跳过则保留本地版本。",
                "When the same URL exists: overwrite updates body and summary; skip keeps the local copy."
              )}
            </p>
          </div>
        </div>
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

function AboutTab(props: { locale: Locale }): JSX.Element {
  const { locale } = props;
  const [desktop, setDesktop] = useState<DesktopAppStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getDesktopAppStatus().then((status) => {
      if (!cancelled) {
        setDesktop(status);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <img src="/on1y-logo.png" alt="On1y" className="h-12 w-12" />
        <h3 className="text-lg font-semibold text-neutral-900">On1y</h3>
        <p className="text-sm leading-relaxed text-neutral-600">
          {L(
            locale,
            "个人知识库：采集 → 正文/字幕 → AI 摘要分类 → 全文检索 → 工作台浏览。",
            "Personal knowledge base: ingest → extract → AI summaries → full-text search → workspace."
          )}
        </p>
        <dl className="space-y-1 text-xs text-neutral-500">
          <div>
            <dt className="inline font-medium">{L(locale, "版本", "Version")}: </dt>
            <dd className="inline">{desktop?.version ?? "—"}</dd>
          </div>
          <div>
            <dt className="inline font-medium">{L(locale, "数据目录", "Data")}: </dt>
            <dd className="inline break-all">{desktop?.data_dir ?? "—"}</dd>
          </div>
          <div>
            <dt className="inline font-medium">{L(locale, "项目路径", "Project")}: </dt>
            <dd className="inline break-all">{desktop?.project_root ?? "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50/80 px-4 py-6">
        <h4 className="text-sm font-medium text-neutral-800">
          {L(locale, "README", "README")}
        </h4>
        <p className="mt-2 text-xs leading-relaxed text-neutral-500">
          {L(
            locale,
            "完整说明文档将在此展示。",
            "Full documentation will appear here."
          )}
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
  const [authRequired, setAuthRequired] = useState(false);
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

      {authRequired ? (
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
      ) : (
        <section className="space-y-2 border-t border-neutral-100 pt-6 text-xs text-neutral-500">
          <p>
            {L(
              locale,
              "当前为单用户免登录模式（ON1Y_AUTH_REQUIRED=false）。要测试多用户，请在 .env 中设置 ON1Y_AUTH_REQUIRED=true 并重启 on1y serve。",
              "Single-user mode (ON1Y_AUTH_REQUIRED=false). Set ON1Y_AUTH_REQUIRED=true in .env and restart on1y serve to test multi-user."
            )}
          </p>
        </section>
      )}
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
  const [cookieBusy, setCookieBusy] = useState<CookiePlatform | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  async function reloadCookies(): Promise<void> {
    const result = await getCookieStatuses();
    setStatuses(result.platforms);
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [settings, cookies] = await Promise.all([getSubscriptionSettings(), getCookieStatuses()]);
        if (cancelled) {
          return;
        }
        setEnabled(settings.enabled_platforms ?? ["bilibili", "youtube", "zhihu"]);
        setSyncSince(settings.bilibili_sync_since ?? settings.youtube_sync_since ?? settings.zhihu_sync_since ?? "");
        setStatuses(cookies.platforms);
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

  function cookieStatusFor(key: CookiePlatform): CookieStatus | undefined {
    return statuses.find((s) => s.platform === key);
  }

  async function onPickCookie(platform: CookiePlatform, file: File | null): Promise<void> {
    if (!file) {
      return;
    }
    setCookieBusy(platform);
    try {
      const result = await uploadCookieFile(platform, file);
      props.onMessage?.(L(locale, `已导入 ${result.count} 条 Cookie`, `Imported ${result.count} cookies`));
      await reloadCookies();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setCookieBusy(null);
    }
  }

  async function onPasteCookie(platform: CookiePlatform): Promise<void> {
    setCookieBusy(platform);
    try {
      const result = await importCookieFromClipboard(platform);
      props.onMessage?.(L(locale, `已从剪贴板导入 ${result.count} 条 Cookie`, `Pasted ${result.count} cookies from clipboard`));
      await reloadCookies();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setCookieBusy(null);
    }
  }

  async function onDeleteCookie(platform: CookiePlatform): Promise<void> {
    setCookieBusy(platform);
    try {
      await deleteCookieFile(platform);
      props.onMessage?.(L(locale, "已删除", "Removed"));
      await reloadCookies();
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setCookieBusy(null);
    }
  }

  function toggle(key: string): void {
    setEnabled((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));
  }

  function sincePayload(since: string): Record<string, string | undefined> {
    return {
      bilibili_sync_since: enabled.includes("bilibili") ? since : undefined,
      youtube_sync_since: enabled.includes("youtube") ? since : undefined,
      zhihu_sync_since: enabled.includes("zhihu") ? since : undefined
    };
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
        ...sincePayload(since)
      });
      props.onMessage?.(L(locale, "订阅设置已保存", "Subscription settings saved"));
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
      const platforms = enabled.filter((p): p is "bilibili" | "youtube" | "zhihu" =>
        ["bilibili", "youtube", "zhihu"].includes(p)
      );
      await saveSubscriptionSettings({
        enabled_platforms: platforms,
        ...sincePayload(since)
      });
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

      <InitialSyncSection locale={locale} statuses={statuses} busy={cookieBusy != null} onClose={props.onClose} />

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{L(locale, "Cookie", "Cookies")}</h3>
        <p className="text-[11px] leading-relaxed text-muted">
          {L(
            locale,
            "用 Cookie-Editor 等扩展导出 JSON，复制到剪贴板后点「粘贴」，或选择 JSON 文件上传。仅保存在本地。",
            "Export JSON with Cookie-Editor, paste from clipboard, or upload a file. Cookies stay on your machine only."
          )}
        </p>
        <div className="space-y-2">
          {COOKIE_PLATFORMS.map((platform) => {
            const status = cookieStatusFor(platform.key);
            const exists = status?.exists ?? false;
            return (
              <div
                key={platform.key}
                className="flex items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
              >
                <span
                  className={`flex h-2 w-2 shrink-0 rounded-full ${exists ? "bg-accent" : "bg-border"}`}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">{platform.label}</div>
                  <div className="text-[11px] text-muted">
                    {exists
                      ? L(
                          locale,
                          `${status?.count ?? 0} 条 · ${status?.updated_at?.replace("T", " ") ?? ""}`,
                          `${status?.count ?? 0} cookies · ${status?.updated_at?.replace("T", " ") ?? ""}`
                        )
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
                  onChange={(e) => void onPickCookie(platform.key, e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
                  disabled={cookieBusy === platform.key}
                  onClick={() => void onPasteCookie(platform.key)}
                  title={L(locale, "从剪贴板粘贴 Cookie JSON", "Paste cookie JSON from clipboard")}
                >
                  {cookieBusy === platform.key ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ClipboardPaste className="h-3.5 w-3.5" />
                  )}
                  {L(locale, "粘贴", "Paste")}
                </button>
                <button
                  type="button"
                  className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
                  disabled={cookieBusy === platform.key}
                  onClick={() => fileInputs.current[platform.key]?.click()}
                >
                  <Upload className="h-3.5 w-3.5" />
                  {L(locale, "文件", "File")}
                </button>
                {exists ? (
                  <button
                    type="button"
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50"
                    disabled={cookieBusy === platform.key}
                    onClick={() => void onDeleteCookie(platform.key)}
                    aria-label="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>

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

      <section className="space-y-2 rounded-lg border border-border bg-panel/80 px-3 py-3 text-xs leading-relaxed text-muted">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground/70">
          {L(locale, "后台同步", "Background sync")}
        </h3>
        <p>
          {L(
            locale,
            "启动后默认先等几分钟再同步；首轮只拉订阅、不入库。大批量入库请在空闲时用「立即同步」或上方的「初始同步」。",
            "After startup, sync waits a few minutes; first tick polls feeds only. For heavy catch-up, use Sync now or Initial sync above."
          )}
        </p>
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

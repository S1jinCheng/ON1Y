"use client";

import {
  FolderOpen,
  Loader2,
  MessageCircle,
  QrCode,
  RefreshCw,
  Smartphone,
  Trash2,
  UserCircle2
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { TelegramLoginDialog } from "@/components/telegram-login-dialog";
import {
  getTelegramAccount,
  getTelegramDialogs,
  getTelegramSettings,
  getTelegramSyncStatus,
  logoutTelegram,
  runTelegramSync,
  saveTelegramSettings,
  type TelegramAccountInfo,
  type TelegramDialog,
  type TelegramSettingsView
} from "@/lib/api";
import { getAuthToken } from "@/lib/auth";
import type { Locale } from "@/lib/i18n";
import { pickFolder } from "@/lib/pick-data-folder";

type Props = {
  locale: Locale;
  onMessage?: (message: string) => void;
};

type LoginMethod = "qr" | "phone";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-accent";
const ghostBtn =
  "rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground hover:bg-soft disabled:opacity-50";
const primaryBtn =
  "rounded-lg border border-foreground bg-inverse px-3 py-2 text-sm text-inverse-foreground hover:opacity-90 disabled:opacity-50";

function FieldLabel(props: { children: React.ReactNode }): JSX.Element {
  return <span className="mb-1.5 block text-xs font-medium text-muted">{props.children}</span>;
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

function clampInt(raw: string, fallback: number, min: number, max: number): number {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return fallback;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, Math.round(parsed)));
}

function useClampedNumberInput(
  value: number,
  onCommit: (next: number) => void,
  min: number,
  max: number
) {
  const [text, setText] = useState(String(value));

  useEffect(() => {
    setText(String(value));
  }, [value]);

  function commit(): number {
    const next = clampInt(text, value, min, max);
    onCommit(next);
    setText(String(next));
    return next;
  }

  return {
    commit,
    inputProps: {
      value: text,
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => setText(e.target.value),
      onBlur: () => {
        commit();
      },
      onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
      }
    }
  };
}

function accountDotClass(account: TelegramAccountInfo | null | undefined, signedIn: boolean): string {
  if (!signedIn) {
    return "bg-border";
  }
  if (account?.valid === true) {
    return "bg-emerald-500";
  }
  if (account?.valid === false) {
    return "bg-red-500";
  }
  return "bg-amber-400";
}

function emptyAccount(detail: string): TelegramAccountInfo {
  return {
    valid: false,
    account_id: null,
    account_name: null,
    username: null,
    avatar_url: null,
    detail,
    verified_at: null
  };
}

function accountSubtitle(
  account: TelegramAccountInfo | null | undefined,
  signedIn: boolean,
  accountLoading: boolean,
  locale: Locale
): string {
  if (!signedIn) {
    return L(locale, "未登录", "Not signed in");
  }
  if (accountLoading) {
    return L(locale, "正在验证…", "Verifying…");
  }
  if (!account) {
    return L(locale, "验证失败，请重新登录", "Verification failed — sign in again");
  }
  if (account.valid === false) {
    return account.detail?.trim() || L(locale, "登录已失效", "Session invalid");
  }
  const name = account.account_name?.trim();
  const username = account.username?.trim();
  if (name && username) {
    return `${name} · @${username}`;
  }
  if (name) {
    return name;
  }
  if (account.account_id) {
    return `ID ${account.account_id}`;
  }
  return L(locale, "已登录", "Signed in");
}

function avatarSrc(account: TelegramAccountInfo | null | undefined): string | null {
  const raw = account?.avatar_url?.trim();
  if (!raw) {
    return null;
  }
  const params = new URLSearchParams();
  const stamp = account?.verified_at?.trim();
  if (stamp) {
    params.set("t", stamp);
  }
  const token = getAuthToken();
  if (token) {
    params.set("access_token", token);
  }
  const query = params.toString();
  return query ? `${raw}?${query}` : raw;
}

export function TelegramSettingsPanel(props: Props): JSX.Element {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [accountBusy, setAccountBusy] = useState(false);
  const [settings, setSettings] = useState<TelegramSettingsView | null>(null);
  const [account, setAccount] = useState<TelegramAccountInfo | null>(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [syncStatus, setSyncStatus] = useState<{
    running: boolean;
    last_report?: Record<string, unknown> | null;
    last_error?: string | null;
  } | null>(null);
  const [dialogs, setDialogs] = useState<TelegramDialog[]>([]);
  const [loadingDialogs, setLoadingDialogs] = useState(false);
  const [loginDialog, setLoginDialog] = useState<{ method: LoginMethod } | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const onMessageRef = useRef(props.onMessage);
  onMessageRef.current = props.onMessage;

  const intervalInput = useClampedNumberInput(
    settings?.interval_seconds ?? 300,
    (next) => setSettings((prev) => (prev ? { ...prev, interval_seconds: next } : prev)),
    15,
    3600
  );
  const sessionGapInput = useClampedNumberInput(
    settings?.session_gap_minutes ?? 30,
    (next) => setSettings((prev) => (prev ? { ...prev, session_gap_minutes: next } : prev)),
    1,
    720
  );

  function applyAccountInfo(info: TelegramAccountInfo, cfg?: TelegramSettingsView | null): void {
    setAccount(info);
    if (info.valid) {
      setSettings((prev) => {
        const base = prev ?? cfg;
        return base ? { ...base, session_authorized: true } : prev;
      });
    } else {
      setSettings((prev) => {
        const base = prev ?? cfg;
        return base ? { ...base, session_authorized: false } : prev;
      });
      setDialogs([]);
    }
  }

  async function reloadAccount(refresh = false): Promise<TelegramAccountInfo | null> {
    setAccountLoading(true);
    try {
      const info = await getTelegramAccount(refresh);
      applyAccountInfo(info);
      return info;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const failed = emptyAccount(message);
      applyAccountInfo(failed);
      onMessageRef.current?.(message);
      return failed;
    } finally {
      setAccountLoading(false);
    }
  }

  async function reloadAll(): Promise<void> {
    const [cfg, status] = await Promise.all([
      getTelegramSettings(),
      getTelegramSyncStatus().catch(() => null)
    ]);
    setSettings(cfg);
    setSyncStatus(status);
    if (cfg.session_authorized && cfg.sync_mode === "client") {
      await reloadAccount(true);
      void loadDialogs(cfg);
    } else {
      setAccount(null);
      setDialogs([]);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const cfg = await getTelegramSettings();
        const status = await getTelegramSyncStatus().catch(() => null);
        if (cancelled) {
          return;
        }
        setSettings(cfg);
        setSyncStatus(status);
        if (cfg.session_authorized && cfg.sync_mode === "client") {
          setAccountLoading(true);
          try {
            const info = await getTelegramAccount(false);
            if (!cancelled) {
              applyAccountInfo(info, cfg);
              if (info.valid) {
                void loadDialogs(cfg);
              }
            }
          } catch (error) {
            if (!cancelled) {
              const message = error instanceof Error ? error.message : String(error);
              applyAccountInfo(emptyAccount(message), cfg);
            }
          } finally {
            if (!cancelled) {
              setAccountLoading(false);
            }
          }
        }
      } catch (error) {
        onMessageRef.current?.(error instanceof Error ? error.message : String(error));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadDialogs(cfg?: TelegramSettingsView): Promise<void> {
    const current = cfg ?? settings;
    if (!current?.session_authorized) {
      return;
    }
    setLoadingDialogs(true);
    try {
      const resp = await getTelegramDialogs();
      setDialogs(resp.dialogs);
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDialogs(false);
    }
  }

  async function openLogin(method: LoginMethod): Promise<void> {
    if (!settings?.api_configured) {
      props.onMessage?.(
        L(
          props.locale,
          "请先在 .env 配置 ON1Y_TELEGRAM_API_ID / ON1Y_TELEGRAM_API_HASH",
          "Configure ON1Y_TELEGRAM_API_ID / ON1Y_TELEGRAM_API_HASH in .env first"
        )
      );
      return;
    }
    if (method === "phone" && settings.session_authorized) {
      setAccountBusy(true);
      try {
        await logoutTelegram();
        setSettings((prev) => (prev ? { ...prev, session_authorized: false } : prev));
        setAccount(null);
        setDialogs([]);
      } catch (err) {
        props.onMessage?.(err instanceof Error ? err.message : String(err));
      } finally {
        setAccountBusy(false);
      }
    }
    setLoginDialog({ method });
  }

  async function onVerifyAccount(): Promise<void> {
    setAccountBusy(true);
    try {
      await reloadAccount(true);
      props.onMessage?.(L(props.locale, "账号信息已更新", "Account info refreshed"));
    } finally {
      setAccountBusy(false);
    }
  }

  async function onLogout(): Promise<void> {
    setAccountBusy(true);
    try {
      await logoutTelegram();
      setSettings((prev) => (prev ? { ...prev, session_authorized: false } : prev));
      setAccount(null);
      setDialogs([]);
      props.onMessage?.(L(props.locale, "已退出 Telegram", "Signed out of Telegram"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setAccountBusy(false);
    }
  }

  async function save(): Promise<void> {
    if (!settings) {
      return;
    }
    setSaving(true);
    try {
      const interval_seconds = intervalInput.commit();
      const session_gap_minutes = sessionGapInput.commit();
      const saved = await saveTelegramSettings({
        ...settings,
        interval_seconds,
        session_gap_minutes
      });
      setSettings(saved);
      props.onMessage?.(L(props.locale, "Telegram 设置已保存", "Telegram settings saved"));
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function syncNow(): Promise<void> {
    setSyncing(true);
    try {
      const kickoff = await runTelegramSync();
      if (!kickoff.started && !kickoff.running) {
        props.onMessage?.(kickoff.message ?? L(props.locale, "同步未启动", "Sync did not start"));
        return;
      }
      for (let i = 0; i < 600; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const status = await getTelegramSyncStatus();
        setSyncStatus(status);
        if (!status.running) {
          if (status.last_error) {
            props.onMessage?.(status.last_error);
            return;
          }
          const report = status.last_report ?? {};
          props.onMessage?.(
            L(
              props.locale,
              `同步完成：导入 ${String(report.imported ?? 0)}，跳过 ${String(report.skipped ?? 0)}，失败 ${String(report.failed ?? 0)}`,
              `Sync done: imported ${String(report.imported ?? 0)}, skipped ${String(report.skipped ?? 0)}, failed ${String(report.failed ?? 0)}`
            )
          );
          return;
        }
      }
      props.onMessage?.(
        L(props.locale, "同步仍在后台进行，请稍后在状态栏查看", "Sync still running in background — check status later")
      );
    } catch (err) {
      props.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  async function browseExportDir(): Promise<void> {
    setBrowsing(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      setSettings((prev) => (prev ? { ...prev, export_dir: picked } : prev));
    } finally {
      setBrowsing(false);
    }
  }

  function toggleChat(chatId: string): void {
    setSettings((prev) => {
      if (!prev) {
        return prev;
      }
      const selected = new Set(prev.sync_chat_ids);
      if (selected.has(chatId)) {
        selected.delete(chatId);
      } else {
        selected.add(chatId);
      }
      return { ...prev, sync_chat_ids: Array.from(selected) };
    });
  }

  if (loading || !settings) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" />
        {L(props.locale, "加载中…", "Loading…")}
      </div>
    );
  }

  const isClient = settings.sync_mode === "client";
  const apiReady = settings.api_configured !== false;
  const signedIn = Boolean(settings.session_authorized);
  const avatar = avatarSrc(account);

  return (
    <section className="space-y-3 rounded-xl border border-border bg-panel/30 p-4">
      <div className="flex items-center gap-2">
        <MessageCircle className="h-4 w-4 text-muted" />
        <h3 className="text-sm font-semibold text-foreground">Telegram</h3>
      </div>

      {!apiReady ? (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-200">
          {L(
            props.locale,
            "服务端未配置 Telegram API。请在 .env 中设置 ON1Y_TELEGRAM_API_ID 与 ON1Y_TELEGRAM_API_HASH，然后重启 on1y serve。",
            "Telegram API is not configured on the server. Set ON1Y_TELEGRAM_API_ID and ON1Y_TELEGRAM_API_HASH in .env, then restart on1y serve."
          )}
        </p>
      ) : null}

      {isClient ? (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5">
          <div className="relative shrink-0">
            {avatar ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatar}
                alt=""
                className="h-9 w-9 rounded-full border border-border object-cover"
              />
            ) : (
              <div className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-soft text-muted">
                <UserCircle2 className="h-5 w-5" />
              </div>
            )}
            <span
              className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${accountDotClass(account, signedIn)}`}
              aria-hidden
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground">Telegram</div>
            <div className="text-[11px] leading-relaxed text-muted">
              {accountSubtitle(account, signedIn, accountLoading, props.locale)}
            </div>
            {account?.verified_at ? (
              <div className="text-[10px] text-muted/70">
                {L(props.locale, "验证", "Verified")}: {account.verified_at.replace("T", " ")}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
            disabled={!apiReady || accountBusy || accountLoading}
            onClick={() => void openLogin("qr")}
            title={L(props.locale, "扫码登录", "QR sign-in")}
          >
            <QrCode className="h-3.5 w-3.5" />
            {L(props.locale, "扫码", "Scan")}
          </button>
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
            disabled={!apiReady || accountBusy || accountLoading}
            onClick={() => void openLogin("phone")}
            title={L(props.locale, "手机号登录", "Phone sign-in")}
          >
            <Smartphone className="h-3.5 w-3.5" />
            {L(props.locale, "手机号", "Phone")}
          </button>
          {signedIn ? (
            <>
              <button
                type="button"
                className={`inline-flex items-center gap-1.5 ${ghostBtn} px-3 py-1.5`}
                disabled={accountBusy || accountLoading}
                onClick={() => void onVerifyAccount()}
                title={L(props.locale, "刷新账号信息", "Refresh account")}
              >
                {accountBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {L(props.locale, "验证", "Verify")}
              </button>
              <button
                type="button"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50"
                disabled={accountBusy}
                onClick={() => void onLogout()}
                aria-label={L(props.locale, "退出登录", "Sign out")}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      <ToggleRow
        label={L(props.locale, "启用自动同步", "Enable auto-sync")}
        description={L(
          props.locale,
          "on1y serve 运行期间定时同步。",
          "Sync periodically while on1y serve is running."
        )}
        checked={settings.enabled}
        disabled={!apiReady}
        onChange={(checked) => setSettings((prev) => (prev ? { ...prev, enabled: checked } : prev))}
      />

      <div>
        <FieldLabel>{L(props.locale, "同步方式", "Sync mode")}</FieldLabel>
        <div className="inline-flex overflow-hidden rounded-lg border border-border text-sm">
          {(
            [
              ["client", L(props.locale, "直连同步", "Direct sync")],
              ["export", L(props.locale, "Desktop 导出", "Desktop export")]
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setSettings((prev) => (prev ? { ...prev, sync_mode: value } : prev))}
              className={`px-3 py-2 transition ${
                settings.sync_mode === value
                  ? "bg-inverse text-inverse-foreground"
                  : "bg-surface text-muted hover:bg-soft"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {isClient && signedIn ? (
        <div className="space-y-2 rounded-lg border border-border bg-panel/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <FieldLabel>{L(props.locale, "要同步的聊天", "Chats to sync")}</FieldLabel>
            <button
              type="button"
              className={ghostBtn}
              disabled={loadingDialogs}
              onClick={() => void loadDialogs()}
            >
              {loadingDialogs
                ? L(props.locale, "加载中…", "Loading…")
                : L(props.locale, "刷新列表", "Refresh")}
            </button>
          </div>
          <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-border p-2">
            {dialogs.length === 0 ? (
              <p className="text-xs text-muted">{L(props.locale, "暂无对话", "No dialogs")}</p>
            ) : (
              dialogs.map((row) => {
                const checked = settings.sync_chat_ids.includes(row.chat_id);
                return (
                  <label
                    key={row.chat_id}
                    className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-soft"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleChat(row.chat_id)}
                    />
                    <span className="min-w-0 flex-1 truncate">{row.title}</span>
                    <span className="text-[10px] text-muted">{row.chat_type}</span>
                  </label>
                );
              })
            )}
          </div>
        </div>
      ) : null}

      {!isClient ? (
        <div>
          <FieldLabel>{L(props.locale, "Telegram 导出目录", "Telegram export folder")}</FieldLabel>
          <div className="flex gap-2">
            <input
              className={`${inputClass} min-w-0 flex-1`}
              value={settings.export_dir}
              onChange={(e) =>
                setSettings((prev) => (prev ? { ...prev, export_dir: e.target.value } : prev))
              }
              placeholder={L(
                props.locale,
                "选择包含 result.json 的文件夹",
                "Folder containing result.json files"
              )}
            />
            <button
              type="button"
              className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
              disabled={browsing}
              onClick={() => void browseExportDir()}
            >
              {browsing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FolderOpen className="h-4 w-4" />
              )}
              {L(props.locale, "浏览…", "Browse…")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <FieldLabel>{L(props.locale, "同步间隔（秒）", "Sync interval (seconds)")}</FieldLabel>
          <input
            type="number"
            min={15}
            max={3600}
            className={inputClass}
            {...intervalInput.inputProps}
          />
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {L(
              props.locale,
              "后台自动同步 Telegram 消息的间隔（15–3600 秒），修改后需点「保存」",
              "Background Telegram sync interval (15–3600 s); click Save to apply"
            )}
          </p>
        </div>
        <div>
          <FieldLabel>{L(props.locale, "会话间隔（分钟）", "Session gap (minutes)")}</FieldLabel>
          <input
            type="number"
            min={1}
            max={720}
            className={inputClass}
            {...sessionGapInput.inputProps}
          />
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {L(
              props.locale,
              "相邻消息超过此间隔则切成新会话归档（1–720 分钟），修改后需点「保存」",
              "Messages farther apart than this start a new archived session (1–720 min); click Save"
            )}
          </p>
        </div>
      </div>

      <ToggleRow
        label={L(props.locale, "同步后自动书面化", "Auto write-up after sync")}
        description={L(
          props.locale,
          "生成 reader_text 书面纪要，并自动分配主题与话题标签",
          "Generate reader_text and assign theme + topic tags"
        )}
        checked={settings.auto_distill}
        onChange={(checked) =>
          setSettings((prev) => (prev ? { ...prev, auto_distill: checked } : prev))
        }
      />

      <ToggleRow
        label={L(props.locale, "自动主题与标签", "Auto theme & tags")}
        description={L(
          props.locale,
          "关闭书面化时仍用 LLM 提取主题标签，便于跨会话关联同话题（需 API Key）",
          "When write-up is off, still classify theme/topic tags to link related sessions (needs API key)"
        )}
        checked={settings.auto_tag ?? true}
        disabled={settings.auto_distill}
        onChange={(checked) =>
          setSettings((prev) => (prev ? { ...prev, auto_tag: checked } : prev))
        }
      />

      {syncStatus?.last_report ? (
        <p className="text-[11px] text-muted">
          {L(props.locale, "上次同步：", "Last sync: ")}
          {String(syncStatus.last_report.scanned ?? 0)}{" "}
          {isClient ? L(props.locale, "个聊天", "chats") : L(props.locale, "个文件", "files")} ·{" "}
          {String(syncStatus.last_report.imported ?? 0)} {L(props.locale, "条导入", "imported")}
        </p>
      ) : null}
      {syncStatus?.last_error ? (
        <p className="text-[11px] text-red-600">{syncStatus.last_error}</p>
      ) : null}

      <div className="flex justify-end gap-2">
        <button type="button" className={ghostBtn} disabled={syncing} onClick={() => void syncNow()}>
          {syncing ? (
            <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 inline h-4 w-4" />
          )}
          {syncing ? L(props.locale, "同步中…", "Syncing…") : L(props.locale, "立即同步", "Sync now")}
        </button>
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(props.locale, "保存中…", "Saving…") : L(props.locale, "保存", "Save")}
        </button>
      </div>

      <TelegramLoginDialog
        locale={props.locale}
        open={loginDialog != null}
        method={loginDialog?.method ?? "qr"}
        forceRelogin
        onClose={() => setLoginDialog(null)}
        onSuccess={() => void reloadAll()}
        onMessage={props.onMessage}
      />
    </section>
  );
}

export function TelegramSettingsButton(_props: {
  locale: Locale;
  onMessage?: (message: string) => void;
}): null {
  return null;
}

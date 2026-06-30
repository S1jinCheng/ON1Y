"use client";

import { FolderOpen, Loader2, MessageCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getTelegramDialogs,
  getTelegramSettings,
  getTelegramSyncStatus,
  runTelegramSync,
  saveTelegramSettings,
  sendTelegramAuthCode,
  signInTelegramAuth,
  type TelegramDialog,
  type TelegramSettingsView
} from "@/lib/api";
import type { Locale } from "@/lib/types";
import { pickFolder } from "@/lib/pick-data-folder";

type Props = {
  locale: Locale;
  onMessage?: (message: string) => void;
};

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

export function TelegramSettingsPanel(props: Props): JSX.Element {
  const { locale, onMessage } = props;
  const [settings, setSettings] = useState<TelegramSettingsView | null>(null);
  const [syncStatus, setSyncStatus] = useState<{
    running: boolean;
    last_report?: Record<string, unknown> | null;
    last_error?: string | null;
  } | null>(null);
  const [dialogs, setDialogs] = useState<TelegramDialog[]>([]);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [loadingDialogs, setLoadingDialogs] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [cfg, status] = await Promise.all([
          getTelegramSettings(),
          getTelegramSyncStatus().catch(() => null)
        ]);
        if (!cancelled) {
          setSettings(cfg);
          setSyncStatus(status);
          if (cfg.session_authorized && cfg.sync_mode === "client") {
            void loadDialogs(cfg);
          }
        }
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
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDialogs(false);
    }
  }

  async function save(): Promise<void> {
    if (!settings) {
      return;
    }
    setSaving(true);
    try {
      const saved = await saveTelegramSettings(settings);
      setSettings(saved);
      onMessage?.(
        L(locale, "Telegram 聊天归档设置已保存", "Telegram chat archive settings saved")
      );
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function syncNow(): Promise<void> {
    setSyncing(true);
    try {
      const report = await runTelegramSync();
      onMessage?.(
        L(
          locale,
          `同步完成：导入 ${report.imported}，跳过 ${report.skipped}，失败 ${report.failed}`,
          `Sync done: imported ${report.imported}, skipped ${report.skipped}, failed ${report.failed}`
        )
      );
      const status = await getTelegramSyncStatus().catch(() => null);
      if (status) {
        setSyncStatus(status);
      }
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
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

  async function sendCode(): Promise<void> {
    setAuthBusy(true);
    try {
      await sendTelegramAuthCode(phone.trim());
      onMessage?.(L(locale, "验证码已发送", "Verification code sent"));
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthBusy(false);
    }
  }

  async function confirmSignIn(): Promise<void> {
    setAuthBusy(true);
    try {
      const result = await signInTelegramAuth({
        phone: phone.trim(),
        code: code.trim(),
        password: password.trim() || undefined
      });
      if (result.ok) {
        const saved = await getTelegramSettings();
        setSettings(saved);
        onMessage?.(L(locale, "Telegram 已登录", "Signed in to Telegram"));
        await loadDialogs(saved);
      }
    } catch (err) {
      onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthBusy(false);
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
        {L(locale, "加载中…", "Loading…")}
      </div>
    );
  }

  const isClient = settings.sync_mode === "client";

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <MessageCircle className="h-4 w-4 text-muted" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
          {L(locale, "聊天归档（Telegram）", "Chat archive (Telegram)")}
        </h3>
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        {L(
          locale,
          "推荐「直连同步」：On1y 在本机通过 Telethon 登录你的 Telegram 账号，定时拉取选中聊天并归档到「聊天」专栏。无需手动导出。",
          "Recommended: Direct sync — On1y logs into Telegram locally via Telethon, pulls selected chats on a schedule, and archives them to Chats. No manual export needed."
        )}
      </p>
      <ToggleRow
        label={L(locale, "启用自动同步", "Enable auto-sync")}
        description={L(
          locale,
          "on1y serve 运行期间定时同步。",
          "Sync periodically while on1y serve is running."
        )}
        checked={settings.enabled}
        onChange={(checked) => setSettings((prev) => (prev ? { ...prev, enabled: checked } : prev))}
      />
      <div>
        <FieldLabel>{L(locale, "同步方式", "Sync mode")}</FieldLabel>
        <div className="inline-flex overflow-hidden rounded-lg border border-border text-sm">
          {(
            [
              ["client", L(locale, "直连同步", "Direct sync")],
              ["export", L(locale, "Desktop 导出", "Desktop export")]
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

      {isClient ? (
        <div className="space-y-3 rounded-lg border border-border bg-panel/40 p-3">
          <p className="text-[11px] text-muted">
            {L(
              locale,
              "在 my.telegram.org 申请 api_id / api_hash，填入下方。Session 保存在本机 data/users/<id>/，不会上传。",
              "Get api_id / api_hash from my.telegram.org. Session stays on this machine under data/users/<id>/."
            )}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel>api_id</FieldLabel>
              <input
                type="number"
                className={inputClass}
                value={settings.api_id ?? ""}
                onChange={(e) =>
                  setSettings((prev) =>
                    prev
                      ? {
                          ...prev,
                          api_id: e.target.value ? Number(e.target.value) : null
                        }
                      : prev
                  )
                }
              />
            </div>
            <div>
              <FieldLabel>api_hash</FieldLabel>
              <input
                type="password"
                className={inputClass}
                value={settings.api_hash}
                onChange={(e) =>
                  setSettings((prev) => (prev ? { ...prev, api_hash: e.target.value } : prev))
                }
              />
            </div>
          </div>
          {!settings.session_authorized ? (
            <div className="space-y-2 border-t border-border pt-3">
              <FieldLabel>{L(locale, "登录 Telegram", "Sign in to Telegram")}</FieldLabel>
              <input
                className={inputClass}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+86..."
              />
              <div className="flex flex-wrap gap-2">
                <button type="button" className={ghostBtn} disabled={authBusy} onClick={() => void sendCode()}>
                  {L(locale, "发送验证码", "Send code")}
                </button>
                <input
                  className={`${inputClass} max-w-[120px]`}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder={L(locale, "验证码", "Code")}
                />
                <input
                  className={`${inputClass} max-w-[160px]`}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={L(locale, "两步验证（如有）", "2FA password")}
                />
                <button type="button" className={primaryBtn} disabled={authBusy} onClick={() => void confirmSignIn()}>
                  {L(locale, "确认登录", "Sign in")}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-emerald-600">
              {L(locale, "已登录 Telegram", "Signed in to Telegram")}
            </p>
          )}
          {settings.session_authorized ? (
            <div className="space-y-2 border-t border-border pt-3">
              <div className="flex items-center justify-between gap-2">
                <FieldLabel>{L(locale, "要同步的聊天", "Chats to sync")}</FieldLabel>
                <button
                  type="button"
                  className={ghostBtn}
                  disabled={loadingDialogs}
                  onClick={() => void loadDialogs()}
                >
                  {loadingDialogs ? L(locale, "加载中…", "Loading…") : L(locale, "刷新列表", "Refresh")}
                </button>
              </div>
              <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-border p-2">
                {dialogs.length === 0 ? (
                  <p className="text-xs text-muted">{L(locale, "暂无对话", "No dialogs")}</p>
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
        </div>
      ) : (
        <div>
          <FieldLabel>{L(locale, "Telegram 导出目录", "Telegram export folder")}</FieldLabel>
          <div className="flex gap-2">
            <input
              className={`${inputClass} min-w-0 flex-1`}
              value={settings.export_dir}
              onChange={(e) =>
                setSettings((prev) => (prev ? { ...prev, export_dir: e.target.value } : prev))
              }
              placeholder={L(locale, "选择包含 result.json 的文件夹", "Folder containing result.json files")}
            />
            <button
              type="button"
              className={`inline-flex shrink-0 items-center gap-1.5 ${ghostBtn} px-3`}
              disabled={browsing}
              onClick={() => void browseExportDir()}
            >
              {browsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
              {L(locale, "浏览…", "Browse…")}
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <FieldLabel>{L(locale, "同步间隔（秒）", "Sync interval (seconds)")}</FieldLabel>
          <input
            type="number"
            min={15}
            max={3600}
            className={inputClass}
            value={settings.interval_seconds}
            onChange={(e) =>
              setSettings((prev) =>
                prev ? { ...prev, interval_seconds: Number(e.target.value) || 300 } : prev
              )
            }
          />
        </div>
        <div>
          <FieldLabel>{L(locale, "会话间隔（分钟）", "Session gap (minutes)")}</FieldLabel>
          <input
            type="number"
            min={1}
            max={720}
            className={inputClass}
            value={settings.session_gap_minutes}
            onChange={(e) =>
              setSettings((prev) =>
                prev ? { ...prev, session_gap_minutes: Number(e.target.value) || 30 } : prev
              )
            }
          />
        </div>
      </div>
      <ToggleRow
        label={L(locale, "同步后自动书面化", "Auto write-up after sync")}
        checked={settings.auto_distill}
        onChange={(checked) =>
          setSettings((prev) => (prev ? { ...prev, auto_distill: checked } : prev))
        }
      />
      {syncStatus?.last_report ? (
        <p className="text-[11px] text-muted">
          {L(locale, "上次同步：", "Last sync: ")}
          {String(syncStatus.last_report.scanned ?? 0)}{" "}
          {isClient ? L(locale, "个聊天", "chats") : L(locale, "个文件", "files")} ·{" "}
          {String(syncStatus.last_report.imported ?? 0)} {L(locale, "条导入", "imported")}
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
          {syncing ? L(locale, "同步中…", "Syncing…") : L(locale, "立即同步", "Sync now")}
        </button>
        <button type="button" className={primaryBtn} disabled={saving} onClick={() => void save()}>
          {saving ? L(locale, "保存中…", "Saving…") : L(locale, "保存", "Save")}
        </button>
      </div>
    </section>
  );
}

"use client";

import React, { useEffect, useState } from "react";
import {
  DeviceSyncStatus, getDeviceSync, resolveDeviceSyncConflict, runDeviceSync, saveDeviceSync
} from "@/lib/api";
import type { Locale } from "@/lib/types";

export function DeviceSyncSettings({ locale }: { locale: Locale }): JSX.Element {
  const zh = locale === "zh";
  const t = (cn: string, en: string): string => zh ? cn : en;
  const [status, setStatus] = useState<DeviceSyncStatus | null>(null);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const inputClass = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
  const buttonClass = "rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-50";

  useEffect(() => {
    let alive = true;
    void getDeviceSync().then((value) => {
      if (!alive) return;
      setStatus(value);
      setUrl(value.server_url);
      setEnabled(value.enabled);
    }).catch((err: unknown) => { if (alive) setError(String(err)); });
    const timer = window.setInterval(() => {
      void getDeviceSync().then((value) => { if (alive) setStatus(value); }).catch(() => {});
    }, 10000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  async function perform(action: () => Promise<DeviceSyncStatus>, success: string): Promise<void> {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setStatus(await action());
      setMessage(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally { setBusy(false); }
  }

  async function save(): Promise<void> {
    if (enabled && !status?.library_id && !window.confirm(t(
      "开启后，当前账号的文章、正文、摘要、笔记、阅读状态、标签和自定义主题会上传到此同步服务。首次同步会合并两端内容，冲突版本会保留。建议先导出备份。是否继续？",
      "Enabling sync uploads this account's articles, notes, summaries, reading state, tags and custom themes to this server. Existing libraries will be merged and conflicts preserved. Export a backup first. Continue?"
    ))) return;
    await perform(async () => {
      const result = await saveDeviceSync({ server_url: url, key, enabled });
      setKey("");
      return result;
    }, t("已保存，开启后每 30 秒尝试同步", "Saved. Sync runs every 30 seconds when enabled."));
  }

  const dirty = status && (url !== status.server_url || enabled !== status.enabled || key !== "");
  return (
    <section className="space-y-3 rounded-xl border border-border bg-panel/60 p-4">
      <h4 className="text-sm font-medium">{t("跨设备同步 · 服务地址", "Cross-device sync · Relay")}</h4>
      <p className="text-xs leading-relaxed text-muted">{t(
        "Win 和 Mac 使用同一个同步地址与配对密钥。本地账号名称可以不同。服务未部署前可保持关闭；不开启不会上传数据。",
        "Use the same server and pairing key on Windows and Mac. Local usernames can differ. Leave disabled until a relay is available; disabled sync uploads nothing."
      )}</p>
      <label className="block space-y-1 text-xs">
        <span>{t("同步服务地址", "Sync server URL")}</span>
        <input aria-label={t("同步服务地址", "Sync server URL")} className={inputClass} value={url}
          placeholder="https://sync.example.com" disabled={busy || !status} onChange={(e) => setUrl(e.target.value)} />
      </label>
      <label className="block space-y-1 text-xs">
        <span>{t("配对密钥", "Pairing key")}</span>
        <input aria-label={t("配对密钥", "Pairing key")} className={inputClass} type="password" autoComplete="new-password"
          value={key} disabled={busy || !status} onChange={(e) => setKey(e.target.value)}
          placeholder={status?.has_key ? t("已保存，留空保持不变", "Saved; leave blank to keep") : t("至少 32 个字符", "At least 32 characters")} />
      </label>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={enabled} disabled={busy || !status} onChange={(e) => setEnabled(e.target.checked)} />
        {t("开启自动同步", "Enable automatic sync")}
      </label>
      <p className="text-xs leading-relaxed text-muted">{t(
        "不包含 Cookie、密码、API Key、书籍、论文附件及本机设置。远程地址必须使用 HTTPS。服务端可读取同步内容，请只连接自己的可信服务。",
        "Excludes cookies, passwords, API keys, books, paper attachments and device settings. Remote servers require HTTPS. The relay can read synced content; use a trusted server."
      )}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={busy || !status} onClick={() => void save()}>{t("保存设置", "Save settings")}</button>
        <button type="button" className={buttonClass} disabled={busy || !status?.enabled || Boolean(dirty)}
          onClick={() => void perform(runDeviceSync, t("本轮同步完成", "Sync round completed"))}>
          {busy ? t("处理中…", "Working…") : t("立即同步", "Sync now")}
        </button>
      </div>
      {status && <div className="space-y-1 text-xs text-muted">
        <p>{t("最后成功同步：", "Last successful sync: ")}{status.last_sync ? new Date(status.last_sync).toLocaleString() : t("尚未同步", "Never")}</p>
        <p>{t("已排队操作：", "Queued operations: ")}{status.pending}{t("，未扫描的本地变化将在下一轮加入", "; unscanned local changes are queued next round")}</p>
      </div>}
      {(error || status?.last_error) && <p role="alert" className="text-xs text-red-600">{error || status?.last_error}</p>}
      {message && <p role="status" className="text-xs text-muted">{message}</p>}
      {!!status?.conflicts.length && <div className="space-y-3 border-t border-border pt-3">
        <h5 className="text-xs font-semibold">{t("需要确认的冲突", "Conflicts to review")} ({status.conflicts.length})</h5>
        <p className="text-xs text-muted">{t("双方内容均已保留。可复制内容手动合并；旧冲突的服务端版本可能已被后续修改。", "Both versions are saved. Copy text to merge manually; the server value may have changed since this conflict.")}</p>
        {status.conflicts.map((conflict) => <details key={conflict.id} className="rounded-lg border border-border p-2 text-xs">
          <summary className="cursor-pointer break-all">{conflict.identity} · {conflict.field}</summary>
          <p className="mt-2 font-medium">{t("冲突时的服务端版本", "Server version at conflict")}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-2">{typeof conflict.current === "string" ? conflict.current : JSON.stringify(conflict.current, null, 2)}</pre>
          <p className="mt-2 font-medium">{t("另一设备提交的版本", "Submitted version")}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-2">{typeof conflict.incoming === "string" ? conflict.incoming : JSON.stringify(conflict.incoming, null, 2)}</pre>
          <div className="mt-2 flex gap-2">
            <button type="button" className={buttonClass} disabled={busy || !status.enabled || Boolean(dirty)}
              onClick={() => void perform(() => resolveDeviceSyncConflict(conflict.id, "current"), t("已保留当前服务端版本", "Kept current server version"))}>{t("保留当前版本", "Keep current")}</button>
            <button type="button" className={buttonClass} disabled={busy || !status.enabled || Boolean(dirty)}
              onClick={() => {
                if (window.confirm(t("使用提交版本替换该字段？", "Replace this field with the submitted version?")))
                  void perform(() => resolveDeviceSyncConflict(conflict.id, "incoming"), t("已采用提交版本", "Used submitted version"));
              }}>{t("采用提交版本", "Use submitted")}</button>
          </div>
        </details>)}
      </div>}
    </section>
  );
}

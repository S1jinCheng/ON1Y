"use client";

import React, { useEffect, useState } from "react";
import {
  type FolderSyncStatus, getFolderSync, saveFolderSync, runFolderSync,
  resolveFolderSync, restoreFolderSync
} from "@/lib/api";
import { pickFolder } from "@/lib/pick-data-folder";
import type { Locale } from "@/lib/types";

export function FolderSyncSettings({ locale }: { locale: Locale }): JSX.Element {
  const t = (cn: string, en: string): string => locale === "zh" ? cn : en;
  const [status, setStatus] = useState<FolderSyncStatus | null>(null);
  const [folder, setFolder] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [create, setCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const button = "rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-50";

  useEffect(() => {
    let alive = true;
    void getFolderSync().then(value => {
      if (!alive) return;
      setStatus(value);
      setFolder(value.folder || value.suggested_folder);
      setEnabled(value.enabled);
    }).catch(err => { if (alive) setError(String(err)); });
    const timer = window.setInterval(() => {
      void getFolderSync().then(value => { if (alive) setStatus(value); }).catch(() => {});
    }, 10000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  async function perform(action: () => Promise<FolderSyncStatus>, success: string): Promise<void> {
    setBusy(true); setError(""); setMessage("");
    try { setStatus(await action()); setMessage(success); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }

  async function save(): Promise<void> {
    if (enabled && !status?.library_id && !window.confirm(t(
      "开启后，当前账户的文章、图书、Paper、笔记、标签及关联的 PDF/电子书会写入所选文件夹，并由 iCloud 上传。首次连接会合并资料。是否继续？",
      "This writes this account's articles, books, papers, notes, tags and linked PDF/ebook files to the selected folder for iCloud to upload. Existing libraries will be merged. Continue?"
    ))) return;
    await perform(async () => {
      const result = await saveFolderSync({ folder, enabled, create });
      setFolder(result.folder); setCreate(false);
      return result;
    }, t("设置已保存。开启后，On1y 运行期间每 30 秒检查一次。", "Saved. While On1y is running, enabled sync checks every 30 seconds."));
  }

  const dirty = Boolean(status && (folder !== status.folder || enabled !== status.enabled));
  const canRun = Boolean(status?.enabled && !busy && !dirty);
  return <section className="space-y-3 rounded-xl border border-border bg-panel/60 p-4">
    <h4 className="text-sm font-medium">{t("iCloud 资料库同步 · 试用", "iCloud library sync · Preview")}</h4>
    <p className="text-xs leading-relaxed text-muted">{t(
      "Mac 和 Windows 选择同一个 iCloud Drive 协议目录。它同步当前账号的文章、书架、Paper、笔记、标签、阅读状态和已关联附件，不会原样镜像 Literature Vault 的目录结构。",
      "Choose the same iCloud Drive protocol folder on Mac and Windows. It syncs supported account records and linked attachments; it does not mirror the Literature Vault directory tree."
    )}</p>
    <label className="block space-y-1 text-xs">
      <span>{t("资料库文件夹", "Library folder")}</span>
      <input aria-label={t("资料库文件夹", "Library folder")} value={folder} disabled={busy || !status}
        onChange={e => setFolder(e.target.value)} placeholder="iCloud Drive / On1y / Library"
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" />
    </label>
    <button className={button} type="button" disabled={busy || !status} onClick={() => void (async () => {
      const path = await pickFolder(); if (path) setFolder(path);
    })()}>{t("选择文件夹", "Choose folder")}</button>
    {!status?.library_id && <label className="flex items-center gap-2 text-xs">
      <input type="checkbox" checked={create} disabled={busy || !status} onChange={e => setCreate(e.target.checked)} />
      {t("在空文件夹创建新资料库，仅第一台电脑勾选", "Create a library in an empty folder, first computer only")}
    </label>}
    <label className="flex items-center gap-2 text-xs">
      <input type="checkbox" checked={enabled} disabled={busy || !status} onChange={e => setEnabled(e.target.checked)} />
      {t("开启文件夹自动同步", "Enable automatic folder sync")}
    </label>
    <p className="text-xs leading-relaxed text-muted">{t(
      "请选择独立的协议专用目录；首次创建必须完全为空，不要选择 Paper 设置中的现有 Literature Vault，也不要放在它的内部。Windows 请设为“始终保留在此设备上”。本机数据库、Cookie、密码和 API Key 不上传；请先关闭下面的服务地址同步。",
      "Use a separate protocol-only folder. First creation requires it to be completely empty; do not choose or nest it inside the existing Literature Vault. On Windows, choose Always keep on this device. Local databases, cookies, passwords and API keys stay local. Disable relay sync below first."
    )}</p>
    <div className="flex flex-wrap gap-2">
      <button className={button} type="button" disabled={busy || !status || !folder.trim()} onClick={() => void save()}>{t("保存文件夹设置", "Save folder settings")}</button>
      <button className={button} type="button" disabled={!canRun} onClick={() => void perform(runFolderSync,
        t("本机同步检查完成。iCloud 的上传和另一台电脑的接收可能仍在进行。", "Local sync check completed. iCloud upload and the other computer's download may still be in progress."))}>
        {busy ? t("处理中…", "Working…") : t("同步资料库", "Sync library")}
      </button>
    </div>
    {status && <div className="space-y-1 text-xs text-muted">
      <p>{t("上次本机检查：", "Last local check: ")}{status.last_sync ? new Date(status.last_sync).toLocaleString() : t("尚未检查", "Never")}</p>
      <p>{t("资料记录：", "Records: ")}{status.records}{t("，待下载附件：", "; pending attachments: ")}{status.pending_files}{t("，待到达的修改：", "; pending changes: ")}{status.pending_events}</p>
    </div>}
    {(error || status?.last_error) && <p role="alert" className="text-xs text-red-600">{error || status?.last_error}</p>}
    {message && <p role="status" className="text-xs text-muted">{message}</p>}
    {!!status?.conflicts.length && <div className="space-y-2 border-t border-border pt-3">
      <h5 className="text-xs font-semibold">{t("需要选择的修改版本", "Choose a version")} ({status.conflicts.length})</h5>
      {status.conflicts.map(c => <details key={c.key + c.field} className="rounded-lg border border-border p-2 text-xs">
        <summary>{c.title} · {c.field}</summary>
        {c.versions.map(v => <div key={v.id} className="mt-2 space-y-1">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words">{typeof v.value === "string" ? v.value : JSON.stringify(v.value, null, 2)}</pre>
          <button className={button} type="button" disabled={!canRun} onClick={() => void perform(
            () => resolveFolderSync(c.key, c.field, v.id), t("已保存选择，将同步到其他设备", "Choice saved for other devices")
          )}>{t("采用此版本", "Use this version")}{v.id === c.winner ? t("（当前显示）", " (currently shown)") : ""}</button>
        </div>)}
      </details>)}
    </div>}
    {!!status?.deleted.length && <details className="border-t border-border pt-3 text-xs">
      <summary>{t("同步回收站", "Sync trash")} ({status.deleted.length})</summary>
      <p className="my-2 text-muted">{t("删除会同步隐藏资料，附件副本暂时保留，可在这里恢复。", "Deletion hides records on other devices. Attachment copies are retained for restoration.")}</p>
      {status.deleted.map(item => <div key={item.key} className="flex items-center justify-between gap-2 py-1">
        <span>{item.title}</span><button className={button} type="button" disabled={!canRun} onClick={() => void perform(
          () => restoreFolderSync(item.key), t("资料已恢复", "Record restored")
        )}>{t("恢复", "Restore")}</button>
      </div>)}
    </details>}
  </section>;
}

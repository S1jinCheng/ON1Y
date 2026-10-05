import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FolderSyncSettings } from "./folder-sync-settings";
import { getFolderSync, runFolderSync, saveFolderSync } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getFolderSync: vi.fn(), saveFolderSync: vi.fn(), runFolderSync: vi.fn(),
  resolveFolderSync: vi.fn(), restoreFolderSync: vi.fn()
}));
vi.mock("@/lib/pick-data-folder", () => ({ pickFolder: vi.fn() }));
const empty = {
  enabled: false, folder: "", suggested_folder: "/iCloud/On1y/Library", library_id: "",
  literature_files_enabled: false, literature_vault: "D:/Literature", literature_files: 0,
  literature_remote_files: 0, literature_excluded: 0, literature_last_scan: null,
  last_sync: null, last_error: null, pending_files: 0, pending_events: 0, records: 0,
  conflicts: [], deleted: []
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getFolderSync).mockResolvedValue(empty);
  vi.mocked(saveFolderSync).mockResolvedValue({ ...empty, folder: "/iCloud/On1y/Library", enabled: true, library_id: "test" });
  vi.mocked(runFolderSync).mockResolvedValue({ ...empty, enabled: true, folder: "/iCloud/On1y/Library", library_id: "test", pending_files: 1 });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("iCloud library settings", () => {
  it("suggests the folder without creating files or starting sync", async () => {
    render(<FolderSyncSettings locale="zh" />);
    await screen.findByDisplayValue("/iCloud/On1y/Library");
    expect(saveFolderSync).not.toHaveBeenCalled();
    expect(runFolderSync).not.toHaveBeenCalled();
  });
  it("requires explicit first-upload consent and distinguishes create from join", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<FolderSyncSettings locale="zh" />);
    await screen.findByDisplayValue("/iCloud/On1y/Library");
    fireEvent.click(screen.getByLabelText("开启文件夹自动同步"));
    fireEvent.click(screen.getByRole("button", { name: "保存文件夹设置" }));
    expect(saveFolderSync).not.toHaveBeenCalled();
    vi.mocked(window.confirm).mockReturnValue(true);
    fireEvent.click(screen.getByLabelText(/仅第一台电脑勾选/));
    fireEvent.click(screen.getByRole("button", { name: "保存文件夹设置" }));
    await waitFor(() => expect(saveFolderSync).toHaveBeenCalledWith({
      folder: "/iCloud/On1y/Library", enabled: true, create: true, literature_files: false
    }));
  });
  it("requires automatic sync and explicit consent before enabling the Literature tree", async () => {
    const scanned = {
      ...empty, enabled: true, folder: "/iCloud/On1y/Library", library_id: "test",
      literature_files: 1608, literature_remote_files: 451, literature_excluded: 23,
      literature_last_scan: "2026-10-05T08:00:00Z"
    };
    vi.mocked(getFolderSync).mockResolvedValue(scanned);
    vi.mocked(saveFolderSync).mockResolvedValue({ ...scanned, literature_files_enabled: true });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<FolderSyncSettings locale="zh" />);
    await screen.findByDisplayValue("/iCloud/On1y/Library");
    const tree = screen.getByLabelText("同步 Literature 文件树（排除数据库与缓存）") as HTMLInputElement;
    expect(tree.disabled).toBe(false);
    fireEvent.click(tree);
    fireEvent.click(screen.getByRole("button", { name: "保存文件夹设置" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("约 2 GB"));
    expect(saveFolderSync).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "保存文件夹设置" }));
    await waitFor(() => expect(saveFolderSync).toHaveBeenCalledWith({
      folder: "/iCloud/On1y/Library", enabled: true, create: false, literature_files: true
    }));
    expect(screen.getByText(/本机文件：1608；协议记录：451；已排除：23/)).toBeTruthy();
    expect(screen.getByText(/Vault 路径：D:\/Literature/)).toBeTruthy();
  });
  it("keeps Literature tree sync unavailable while automatic sync is off", async () => {
    render(<FolderSyncSettings locale="en" />);
    await screen.findByDisplayValue("/iCloud/On1y/Library");
    const tree = screen.getByLabelText("Sync Literature file tree (excluding databases and caches)") as HTMLInputElement;
    expect(tree.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Enable automatic folder sync"));
    expect(tree.disabled).toBe(false);
  });
  it("does not present a local check as cloud delivery confirmation", async () => {
    vi.mocked(getFolderSync).mockResolvedValue({ ...empty, enabled: true, folder: "/iCloud/On1y/Library", library_id: "test" });
    render(<FolderSyncSettings locale="zh" />);
    await screen.findByDisplayValue("/iCloud/On1y/Library");
    fireEvent.click(screen.getByRole("button", { name: "同步资料库" }));
    await screen.findByText(/iCloud 的上传和另一台电脑的接收可能仍在进行/);
    expect(runFolderSync).toHaveBeenCalledOnce();
  });
  it("displays conflict contents without executing markup", async () => {
    vi.mocked(getFolderSync).mockResolvedValue({ ...empty, conflicts: [{
      key: "k", title: "Paper", field: "meta/user_note_html", winner: "v",
      versions: [{ id: "v", value: "<img src=x onerror=alert(1)>" }]
    }] });
    const { container } = render(<FolderSyncSettings locale="zh" />);
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
  });
});

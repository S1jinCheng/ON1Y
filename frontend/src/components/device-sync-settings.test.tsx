import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeviceSyncSettings } from "./device-sync-settings";
import { getDeviceSync, runDeviceSync, saveDeviceSync } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getDeviceSync: vi.fn(), saveDeviceSync: vi.fn(), runDeviceSync: vi.fn(),
  resolveDeviceSyncConflict: vi.fn()
}));

const empty = {
  enabled: false, server_url: "", has_key: false, device_id: "device",
  library_id: "", last_sync: null, last_error: null, pending: 0, conflicts: []
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getDeviceSync).mockResolvedValue(empty);
  vi.mocked(saveDeviceSync).mockResolvedValue(empty);
  vi.mocked(runDeviceSync).mockResolvedValue(empty);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("personal device sync settings", () => {
  it("does not send data when opened and masks the pairing key", async () => {
    render(<DeviceSyncSettings locale="zh" />);
    await screen.findByText(/尚未同步/);
    expect((screen.getByLabelText("配对密钥") as HTMLInputElement).type).toBe("password");
    expect(saveDeviceSync).not.toHaveBeenCalled();
    expect(runDeviceSync).not.toHaveBeenCalled();
  });

  it("requires consent before enabling the first upload", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<DeviceSyncSettings locale="zh" />);
    await screen.findByText(/尚未同步/);
    fireEvent.click(screen.getByLabelText("开启自动同步"));
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(saveDeviceSync).not.toHaveBeenCalled();
  });

  it("saves the endpoint and key after consent, then clears the input", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DeviceSyncSettings locale="zh" />);
    await screen.findByText(/尚未同步/);
    fireEvent.change(screen.getByLabelText("同步服务地址"), { target: { value: "https://sync.example.com" } });
    fireEvent.change(screen.getByLabelText("配对密钥"), { target: { value: "secret-key" } });
    fireEvent.click(screen.getByLabelText("开启自动同步"));
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(saveDeviceSync).toHaveBeenCalledWith({
      server_url: "https://sync.example.com", key: "secret-key", enabled: true
    }));
    await waitFor(() => expect((screen.getByLabelText("配对密钥") as HTMLInputElement).value).toBe(""));
  });

  it("renders conflict HTML as inert text, never executable markup", async () => {
    vi.mocked(getDeviceSync).mockResolvedValue({ ...empty, conflicts: [{
      id: "conflict", identity: "article", field: "meta/user_note_html", device_id: "other",
      current: "<img src=x onerror=alert(1)>", incoming: "<script>bad()</script>"
    }] });
    const { container } = render(<DeviceSyncSettings locale="zh" />);
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});

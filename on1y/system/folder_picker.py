"""Native folder picker for local server (web UI on same machine)."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def _enable_win_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _pick_folder_win32(title: str) -> str | None:
    """Windows IFileOpenDialog — same sharp UI as Explorer (HiDPI-safe)."""
    import ctypes
    import uuid
    from ctypes import POINTER, Structure, byref, c_void_p, cast, windll
    from ctypes.wintypes import BYTE, DWORD, HRESULT, HWND, LPCWSTR, WORD

    class GUID(Structure):
        _fields_ = [
            ("Data1", DWORD),
            ("Data2", WORD),
            ("Data3", WORD),
            ("Data4", BYTE * 8),
        ]

    def guid_from(text: str) -> GUID:
        return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)

    CLSCTX_INPROC_SERVER = 0x1
    COINIT_APARTMENTTHREADED = 0x2
    FOS_PICKFOLDERS = 0x20
    FOS_FORCEFILESYSTEM = 0x40
    FOS_PATHMUSTEXIST = 0x800
    SIGDN_FILESYSPATH = 0x80058000
    S_OK = 0
    HRESULT_CANCELLED = 0x800704C7

    ole32 = windll.ole32
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dialog = c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            byref(guid_from("DC1C5A9C-E88A-4DDE-B5A1-0F365D77D938")),
            None,
            CLSCTX_INPROC_SERVER,
            byref(guid_from("D57C7288-D4AD-4768-BE02-9D969532D960")),
            byref(dialog),
        )
        if hr != S_OK or not dialog.value:
            return None

        def vfn(index: int, restype, *argtypes):
            vtbl = cast(dialog, POINTER(POINTER(c_void_p))).contents[0]
            proto = ctypes.CFUNCTYPE(restype, c_void_p, *argtypes)
            return proto(vtbl[index])

        set_options = vfn(9, HRESULT, DWORD)
        set_title = vfn(17, HRESULT, LPCWSTR)
        show = vfn(3, HRESULT, HWND)
        get_result = vfn(20, HRESULT, POINTER(c_void_p))

        hr = set_options(
            dialog,
            FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST,
        )
        if hr != S_OK:
            return None
        if title:
            set_title(dialog, title)
        hr = show(dialog, None)
        if hr == HRESULT_CANCELLED:
            return None
        if hr != S_OK:
            return None

        item = c_void_p()
        hr = get_result(dialog, byref(item))
        if hr != S_OK or not item.value:
            return None

        get_display_name = cast(
            cast(item, POINTER(POINTER(c_void_p))).contents[0][5],
            ctypes.CFUNCTYPE(HRESULT, c_void_p, DWORD, POINTER(ctypes.c_wchar_p)),
        )
        psz = ctypes.c_wchar_p()
        hr = get_display_name(item, SIGDN_FILESYSPATH, byref(psz))
        if hr != S_OK or not psz.value:
            return None
        return psz.value.strip() or None
    finally:
        if dialog.value:
            release = cast(
                cast(dialog, POINTER(POINTER(c_void_p))).contents[0][2],
                ctypes.CFUNCTYPE(ctypes.c_ulong, c_void_p),
            )
            release(dialog)
        ole32.CoUninitialize()


def _pick_folder_tkinter(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        logger.warning("tkinter unavailable for folder picker: %s", exc)
        return None

    _enable_win_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        path = filedialog.askdirectory(parent=root, title=title)
    finally:
        root.destroy()
    cleaned = (path or "").strip()
    return cleaned or None


def pick_folder_dialog(title: str = "选择文件夹") -> str | None:
    """Open OS folder dialog; returns absolute path or None if cancelled."""
    if sys.platform == "win32":
        try:
            path = _pick_folder_win32(title)
            if path:
                return path
        except Exception as exc:
            logger.warning("Windows IFileOpenDialog failed, falling back to tkinter: %s", exc)
    return _pick_folder_tkinter(title)

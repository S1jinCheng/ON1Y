"""macOS Chromium is staged intact, not processed as individual Mach-O files."""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("playwright", excludes=["driver/package/.local-browsers/**"])

"""Platform integration tests with no changes to real login items or user data."""

from __future__ import annotations

import plistlib

import pytest
from on1y.app_update import _pick_setup_asset
from on1y.config import Settings
from on1y.desktop import autostart
from on1y.desktop.launch_prefs import write_launch_prefs


def test_macos_paper_vault_default_is_in_user_data(monkeypatch, tmp_path):
    from on1y.papers import settings_store

    monkeypatch.setattr(settings_store.sys, "platform", "darwin")
    monkeypatch.setattr(settings_store, "user_dir", lambda uid: tmp_path / str(uid))
    settings = settings_store.load_paper_settings(7)
    assert settings.literature_vault_path == str(tmp_path / "7/papers/Literature")
    assert settings_store.resolve_literature_vault(7) == tmp_path / "7/papers/Literature"


def test_macos_legacy_default_does_not_write_to_application(monkeypatch, tmp_path):
    from on1y.papers import settings_store

    monkeypatch.setattr(settings_store.sys, "platform", "darwin")
    monkeypatch.setattr(settings_store, "user_dir", lambda uid: tmp_path / str(uid))
    settings_store.save_paper_settings(
        7, settings_store.PaperSettings(literature_vault_path=r"E:\Literature")
    )
    assert settings_store.resolve_literature_vault(7) == tmp_path / "7/papers/Literature"
    with pytest.raises(ValueError, match="Windows"):
        settings_store.resolve_literature_vault(7, r"D:\custom-vault")
    custom = tmp_path / "My Papers"
    settings_store.save_paper_settings(
        7, settings_store.PaperSettings(literature_vault_path=str(custom))
    )
    assert settings_store.resolve_literature_vault(7) == custom


def test_windows_paper_vault_default_is_unchanged(monkeypatch):
    from on1y.papers import settings_store

    monkeypatch.setattr(settings_store.sys, "platform", "win32")
    assert settings_store.PaperSettings().literature_vault_path == r"E:\Literature"


def test_macos_login_agent_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    executable = tmp_path / "On1y Test.app" / "Contents" / "MacOS" / "On1y"
    executable.parent.mkdir(parents=True)
    executable.touch()
    agent = tmp_path / "LaunchAgents" / "app.on1y.desktop.plist"
    monkeypatch.setenv("ON1Y_DESKTOP_EXECUTABLE", str(executable))
    monkeypatch.setattr(autostart, "_agent_path", lambda: agent)
    assert autostart.autostart_supported()
    assert not autostart.autostart_installed()
    assert autostart.set_autostart(True)
    payload = plistlib.loads(agent.read_bytes())
    assert payload["ProgramArguments"] == [str(executable), "--autostart"]
    assert payload["RunAtLoad"] is True
    assert agent.stat().st_mode & 0o777 == 0o600
    assert not autostart.set_autostart(False)
    assert not agent.exists()


def test_macos_browser_mode_has_no_login_startup(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.delenv("ON1Y_DESKTOP_EXECUTABLE", raising=False)
    assert not autostart.autostart_supported()


@pytest.mark.parametrize("architecture,expected", [("arm64", "aarch64"), ("x86_64", "x64")])
def test_update_selects_matching_mac_architecture(monkeypatch, architecture, expected):
    monkeypatch.setattr("on1y.app_update.sys.platform", "darwin")
    monkeypatch.setattr("on1y.app_update.platform.machine", lambda: architecture)
    assets = [
        {"name": f"On1y_0.2.0_{suffix}"}
        for suffix in ("x64-setup.exe", "x64.dmg", "aarch64.dmg", "universal.dmg")
    ]
    assert _pick_setup_asset(assets)["name"] == f"On1y_0.2.0_{expected}.dmg"
    assert _pick_setup_asset(assets[:1]) is None
    assert _pick_setup_asset(assets[-1:]) == assets[-1]


def test_packaged_preferences_do_not_write_into_app_bundle(monkeypatch, tmp_path):
    install = tmp_path / "On1y.app" / "Contents" / "Resources" / "app"
    bootstrap = tmp_path / "Application Support" / "On1y" / "data" / "app-launch.json"
    chosen_data = tmp_path / "External Disk" / "Knowledge"
    monkeypatch.setattr("on1y.config.PROJECT_ROOT", install)
    monkeypatch.setenv("ON1Y_LAUNCH_PREFS_FILE", str(bootstrap))
    settings = Settings(data_dir=chosen_data)
    prefs = write_launch_prefs(data_dir_override=str(chosen_data), settings=settings)
    assert prefs["data_dir_override"] == str(chosen_data)
    assert bootstrap.read_bytes() == (chosen_data / "app-launch.json").read_bytes()
    assert not install.exists()


def test_macos_system_proxy(monkeypatch):
    from on1y.network.proxy import detect_system_proxy

    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("urllib.request.getproxies", lambda: {"https": "127.0.0.1:7890"})
    assert detect_system_proxy() == "http://127.0.0.1:7890"


def test_macos_model_directory_supports_unicode(monkeypatch, tmp_path):
    from on1y.papers import figures

    monkeypatch.setattr("sys.platform", "darwin")
    settings = Settings(data_dir=tmp_path / "知识库")
    monkeypatch.setattr(figures, "get_settings", lambda: settings)
    assert figures._ascii_model_root() == settings.data_dir / "models"
    assert (settings.data_dir / "models").is_dir()


@pytest.mark.parametrize("single_user", ["true", "false"])
def test_fresh_install_does_not_sync_nonexistent_user(monkeypatch, tmp_path, single_user):
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.config import get_settings
    from on1y.sync_settings.settings import any_economist_auto_sync_enabled
    from on1y.user.accounts import list_sync_user_ids

    monkeypatch.setenv("ON1Y_DB_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ON1Y_SINGLE_USER_MODE", single_user)
    get_settings.cache_clear()
    storage = get_storage()
    try:
        assert list_sync_user_ids(storage) == []
        assert not any_economist_auto_sync_enabled()
    finally:
        storage.close()
        get_settings.cache_clear()

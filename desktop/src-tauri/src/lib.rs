mod boot;

use std::sync::Mutex;

use boot::{
    boot, find_on1y_root, prepare_portable_runtime, read_close_window_action,
    read_open_window_pref, resolve_runtime_layout, BootConfig, ManagedServers,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    webview::NewWindowResponse,
    AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_opener::OpenerExt;

struct AppState {
    servers: Mutex<Option<ManagedServers>>,
    frontend_url: Mutex<Option<String>>,
    on1y_root: Mutex<String>,
    bundled: Mutex<bool>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let autostart = std::env::args().any(|a| a == "--autostart");

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            open_external_url,
            open_zotero_pdf,
            pick_data_folder,
            save_archive_file
        ])
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            focus_main_window(app);
        }))
        .manage(AppState {
            servers: Mutex::new(None),
            frontend_url: Mutex::new(None),
            on1y_root: Mutex::new(String::new()),
            bundled: Mutex::new(false),
        })
        .setup(move |app| {
            let resource_dir = app.path().resource_dir().ok();
            let (root, backend_exe, bundled) = resolve_runtime_layout(resource_dir);
            let data_dir = prepare_portable_runtime(&root, bundled);
            std::env::set_var("ON1Y_ROOT", &root);
            if let Some(state) = app.try_state::<AppState>() {
                *state.on1y_root.lock().unwrap() = root.to_string_lossy().into_owned();
                *state.bundled.lock().unwrap() = bundled;
            }
            let open_window = if autostart {
                read_open_window_pref(&root, bundled)
            } else {
                true
            };
            let boot_config = BootConfig {
                root: root.clone(),
                data_dir,
                backend_exe,
                bundled,
                open_window,
            };
            setup_tray(app.handle())?;
            create_splash_window(app.handle())?;
            let handle = app.handle().clone();
            let cfg = boot_config;
            std::thread::spawn(move || {
                if let Err(err) = run_boot_sequence(&handle, &cfg) {
                    let message = err.to_string();
                    let handle_for_err = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        show_boot_error(&handle_for_err, &message);
                    });
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    if let Ok(mut guard) = state.servers.lock() {
                        if let Some(mut servers) = guard.take() {
                            servers.stop_started();
                        }
                    }
                }
            }
        });
}

const SPLASH_LABEL: &str = "splash";
const MAIN_LABEL: &str = "main";

fn create_splash_window(app: &AppHandle) -> tauri::Result<()> {
    let _window =
        WebviewWindowBuilder::new(app, SPLASH_LABEL, WebviewUrl::App("index.html".into()))
            .title("On1y")
            .inner_size(1320.0, 880.0)
            .min_inner_size(960.0, 640.0)
            .center()
            .build()?;
    Ok(())
}

fn dismiss_splash(app: &AppHandle) {
    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        let _ = splash.destroy();
    }
}

fn create_workbench_window(app: &AppHandle, frontend_url: &str, show: bool) -> Result<(), String> {
    let boot_ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let target = format!("{frontend_url}/?on1y_boot={boot_ts}");
    let parsed = Url::parse(&target).map_err(|e| e.to_string())?;
    let webview_url = WebviewUrl::External(parsed);

    dismiss_splash(app);

    let app_for_nav = app.clone();
    let app_for_popup = app.clone();
    let window = WebviewWindowBuilder::new(app, MAIN_LABEL, webview_url)
        .title("On1y")
        .inner_size(1320.0, 880.0)
        .min_inner_size(960.0, 640.0)
        .center()
        .visible(show)
        .on_navigation(move |url| handle_navigation(&app_for_nav, &url))
        .on_new_window(move |url, _features| {
            open_url_in_browser(&app_for_popup, &url);
            NewWindowResponse::Deny
        })
        .build()
        .map_err(|e| format!("无法创建工作台窗口: {e}"))?;
    let (root_str, bundled) = app
        .try_state::<AppState>()
        .map(|state| {
            (
                state.on1y_root.lock().unwrap().clone(),
                *state.bundled.lock().unwrap(),
            )
        })
        .unwrap_or_else(|| (find_on1y_root().to_string_lossy().to_string(), false));
    attach_close_handler(&window, &root_str, bundled);
    if show {
        let _ = window.set_focus();
    }
    Ok(())
}

fn is_internal_app_url(url: &Url) -> bool {
    let scheme = url.scheme();
    if scheme == "tauri" || scheme == "asset" || scheme == "data" {
        return true;
    }
    if scheme != "http" && scheme != "https" {
        return false;
    }
    match url.host_str() {
        // Tauri 2 serves bundled UI at http://tauri.localhost/ (not a public website).
        Some("127.0.0.1") | Some("localhost") | Some("[::1]") | Some("tauri.localhost") => true,
        _ => false,
    }
}

fn open_url_in_browser(app: &AppHandle, url: &Url) {
    if is_internal_app_url(url) {
        return;
    }
    let scheme = url.scheme();
    if scheme != "http" && scheme != "https" {
        return;
    }
    let target = url.to_string();
    let _ = app.opener().open_url(target, None::<&str>);
}

fn handle_navigation(app: &AppHandle, url: &Url) -> bool {
    if is_internal_app_url(url) {
        return true;
    }
    if url.scheme() == "http" || url.scheme() == "https" {
        open_url_in_browser(app, url);
        return false;
    }
    false
}

fn run_boot_sequence(
    app: &AppHandle,
    config: &BootConfig,
) -> Result<(), Box<dyn std::error::Error>> {
    match boot(config) {
        Ok((servers, frontend_url)) => {
            if let Some(state) = app.try_state::<AppState>() {
                *state.frontend_url.lock().unwrap() = Some(frontend_url.clone());
                *state.servers.lock().unwrap() = Some(servers);
            }
            let app = app.clone();
            let show = config.open_window;
            let _ = app.clone().run_on_main_thread(move || {
                if let Err(err) = open_workspace(&app, &frontend_url, show) {
                    show_boot_error(&app, &err);
                }
            });
            Ok(())
        }
        Err(err) => {
            show_boot_error(app, &err.to_string());
            Err(err.into())
        }
    }
}

fn open_workspace(app: &AppHandle, frontend_url: &str, show: bool) -> Result<(), String> {
    create_workbench_window(app, frontend_url, show)
}

fn stop_managed_servers(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut guard) = state.servers.lock() {
            if let Some(mut servers) = guard.take() {
                servers.stop_started();
            }
        }
    }
}

fn attach_close_handler(window: &tauri::WebviewWindow, root: &str, bundled: bool) {
    let w = window.clone();
    let root = root.to_string();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            let action = read_close_window_action(std::path::Path::new(&root), bundled);
            api.prevent_close();
            if action == "quit" {
                let app = w.app_handle().clone();
                stop_managed_servers(&app);
                app.exit(0);
            } else {
                let _ = w.hide();
            }
        }
    });
}

fn show_boot_error(app: &AppHandle, message: &str) {
    let escaped = message
        .replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\r', " ")
        .replace('\n', "\\n");
    let script = format!("window.__ON1Y_SHOW_ERROR__ && window.__ON1Y_SHOW_ERROR__('{escaped}');");
    if let Some(window) = app
        .get_webview_window(SPLASH_LABEL)
        .or_else(|| app.get_webview_window(MAIN_LABEL))
    {
        let _ = window.show();
        let _ = window.eval(&script);
    }
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        return;
    }
    if let Some(state) = app.try_state::<AppState>() {
        if let Some(url) = state.frontend_url.lock().unwrap().clone() {
            let _ = open_workspace(app, &url, true);
        }
    }
}

#[tauri::command]
fn pick_data_folder() -> Option<String> {
    rfd::FileDialog::new()
        .set_title("选择 On1y 数据目录")
        .pick_folder()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn save_archive_file(default_name: String, data: Vec<u8>) -> Option<String> {
    let path = rfd::FileDialog::new()
        .set_title("保存知识库导出")
        .set_file_name(default_name.trim())
        .add_filter("On1y Archive", &["on1y.zip", "zip"])
        .save_file()?;
    std::fs::write(&path, data).ok()?;
    Some(path.to_string_lossy().into_owned())
}

#[tauri::command]
fn open_external_url(app: AppHandle, url: String) -> Result<(), String> {
    let trimmed = url.trim();
    if !(trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
        return Err("only http(s) URLs are allowed".into());
    }
    app.opener()
        .open_url(trimmed, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn open_zotero_pdf(app: AppHandle, url: String) -> Result<(), String> {
    let trimmed = url.trim();
    if !valid_zotero_reader_url(trimmed) {
        return Err("invalid Zotero reader URL".into());
    }
    app.opener()
        .open_url(trimmed, None::<&str>)
        .map_err(|e| e.to_string())
}

fn valid_zotero_reader_url(value: &str) -> bool {
    let Ok(parsed) = Url::parse(value) else {
        return false;
    };
    let segments = parsed
        .path_segments()
        .map(|parts| parts.collect::<Vec<_>>())
        .unwrap_or_default();
    let personal = segments.len() == 3
        && segments[0] == "library"
        && segments[1] == "items"
        && valid_zotero_key(segments[2]);
    let group = segments.len() == 4
        && segments[0] == "groups"
        && segments[1].chars().all(|ch| ch.is_ascii_digit())
        && !segments[1].is_empty()
        && segments[2] == "items"
        && valid_zotero_key(segments[3]);
    parsed.scheme() == "zotero"
        && parsed.host_str() == Some("open-pdf")
        && parsed.query().is_none()
        && parsed.fragment().is_none()
        && (personal || group)
}

fn valid_zotero_key(value: &str) -> bool {
    !value.is_empty() && value.len() <= 100 && value.chars().all(|ch| ch.is_ascii_alphanumeric())
}

#[cfg(test)]
mod zotero_reader_tests {
    use super::valid_zotero_reader_url;

    #[test]
    fn accepts_personal_and_group_pdf_links() {
        assert!(valid_zotero_reader_url(
            "zotero://open-pdf/library/items/ABCD1234"
        ));
        assert!(valid_zotero_reader_url(
            "zotero://open-pdf/groups/42/items/PDF123"
        ));
    }

    #[test]
    fn rejects_non_reader_and_untrusted_links() {
        assert!(!valid_zotero_reader_url(
            "https://open-pdf/library/items/ABCD1234"
        ));
        assert!(!valid_zotero_reader_url(
            "zotero://select/library/items/ABCD1234"
        ));
        assert!(!valid_zotero_reader_url(
            "zotero://open-pdf/groups/not-a-group/items/PDF123"
        ));
        assert!(!valid_zotero_reader_url(
            "zotero://open-pdf/library/items/../../bad"
        ));
    }
}

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let show_i = MenuItem::with_id(app, "show", "打开 On1y", true, None::<&str>)?;
    let quit_i = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => focus_main_window(app),
            "quit" => {
                stop_managed_servers(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                focus_main_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

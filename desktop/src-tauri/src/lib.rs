mod boot;

use std::sync::Mutex;

use boot::{boot, find_on1y_root, read_open_window_pref, BootConfig, ManagedServers};
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
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let autostart = std::env::args().any(|a| a == "--autostart");
    let root = find_on1y_root();
    std::env::set_var("ON1Y_ROOT", &root);

    let boot_config = BootConfig {
        root: root.clone(),
        autostart,
        open_window: read_open_window_pref(&root),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![open_external_url])
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            focus_main_window(app);
        }))
        .manage(AppState {
            servers: Mutex::new(None),
            frontend_url: Mutex::new(None),
        })
        .setup(move |app| {
            create_main_window(app.handle())?;
            setup_tray(app.handle())?;
            let handle = app.handle().clone();
            let cfg = boot_config.clone();
            std::thread::spawn(move || {
                if let Err(err) = run_boot_sequence(&handle, &cfg) {
                    show_boot_error(&handle, &err.to_string());
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

fn create_main_window(app: &AppHandle) -> tauri::Result<()> {
    let app_for_nav = app.clone();
    let app_for_popup = app.clone();
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("On1y")
        .inner_size(1320.0, 880.0)
        .min_inner_size(960.0, 640.0)
        .center()
        .on_navigation(move |url| handle_navigation(&app_for_nav, &url))
        .on_new_window(move |url, _features| {
            open_url_in_browser(&app_for_popup, &url);
            NewWindowResponse::Deny
        })
        .build()?;
    attach_hide_on_close(&window);
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

fn run_boot_sequence(app: &AppHandle, config: &BootConfig) -> Result<(), Box<dyn std::error::Error>> {
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
    let parsed = Url::parse(frontend_url).map_err(|e| e.to_string())?;
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口未创建".to_string())?;
    window
        .navigate(parsed)
        .map_err(|e| format!("无法打开工作台: {e}"))?;
    if show {
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        let _ = window.hide();
    }
    Ok(())
}

fn attach_hide_on_close(window: &tauri::WebviewWindow) {
    let w = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = w.hide();
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
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.eval(&script);
    }
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
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
fn open_external_url(app: AppHandle, url: String) -> Result<(), String> {
    let trimmed = url.trim();
    if !(trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
        return Err("only http(s) URLs are allowed".into());
    }
    app.opener()
        .open_url(trimmed, None::<&str>)
        .map_err(|e| e.to_string())
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
                if let Some(state) = app.try_state::<AppState>() {
                    if let Ok(mut guard) = state.servers.lock() {
                        if let Some(mut servers) = guard.take() {
                            servers.stop_started();
                        }
                    }
                }
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

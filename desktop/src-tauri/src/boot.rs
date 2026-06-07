use std::fs;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use reqwest::blocking::Client;
use serde::Deserialize;

const DEFAULT_BACKEND_PORT: u16 = 8765;

fn backend_port(root: &Path, data_dir: &Path) -> u16 {
    if let Ok(port_str) = std::env::var("ON1Y_WEB_PORT") {
        if let Ok(port) = port_str.trim().parse::<u16>() {
            return port;
        }
    }
    for env_path in [data_dir.parent().map(|p| p.join(".env")), Some(root.join(".env"))] {
        let Some(env_path) = env_path else { continue };
        if let Ok(text) = fs::read_to_string(env_path) {
            for line in text.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                let Some((key, value)) = line.split_once('=') else {
                    continue;
                };
                if key.trim() == "ON1Y_WEB_PORT" {
                    if let Ok(port) = value.trim().parse::<u16>() {
                        return port;
                    }
                }
            }
        }
    }
    DEFAULT_BACKEND_PORT
}

#[derive(Clone)]
pub struct BootConfig {
    pub root: PathBuf,
    pub data_dir: PathBuf,
    pub backend_exe: Option<PathBuf>,
    pub bundled: bool,
    pub open_window: bool,
}

pub struct ManagedServers {
    pub backend: Option<Child>,
    pub started_backend: bool,
}

impl ManagedServers {
    pub fn stop_started(&mut self) {
        if self.started_backend {
            stop_child(&mut self.backend);
        }
    }
}

impl Drop for ManagedServers {
    fn drop(&mut self) {
        self.stop_started();
    }
}

#[derive(Debug)]
pub enum BootError {
    Message(String),
}

impl BootError {
    fn msg(text: impl Into<String>) -> Self {
        Self::Message(text.into())
    }
}

impl std::fmt::Display for BootError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Message(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for BootError {}

/// Resolve app root + optional bundled backend from Tauri resources (release install).
pub fn resolve_runtime_layout(resource_dir: Option<PathBuf>) -> (PathBuf, Option<PathBuf>, bool) {
    if let Some(res_dir) = resource_dir {
        let app_root = res_dir.join("app");
        let backend_exe = res_dir.join("backend").join("on1y").join("on1y.exe");
        let frontend = app_root.join("frontend").join("out").join("index.html");
        if frontend.is_file() && backend_exe.is_file() {
            return (app_root, Some(backend_exe), true);
        }
    }
    let root = find_dev_root();
    (root, None, false)
}

/// Create writable user data + config for packaged installs.
pub fn prepare_portable_runtime(app_root: &Path, bundled: bool) -> PathBuf {
    let data_dir = resolve_data_dir_for_prefs(app_root, bundled);
    let _ = fs::create_dir_all(&data_dir);

    if !bundled {
        return data_dir;
    }

    let (config_dir, env_path) = resolve_user_config_paths(&data_dir, app_root, bundled);
    let _ = fs::create_dir_all(&config_dir);

    let feeds = config_dir.join("feeds.yaml");
    if !feeds.is_file() {
        let example = app_root.join("config").join("feeds.yaml.example");
        if example.is_file() {
            let _ = fs::copy(example, &feeds);
        }
    }

    if !env_path.is_file() {
        let example = app_root.join(".env.example");
        let mut body = if example.is_file() {
            fs::read_to_string(example).unwrap_or_default()
        } else {
            String::new()
        };
        if !body.contains("ON1Y_AUTH_SECRET_KEY") {
            body.push_str("\nON1Y_AUTH_SECRET_KEY=");
            body.push_str(&random_secret());
            body.push('\n');
        }
        let _ = fs::write(&env_path, body);
    }

    data_dir
}

pub fn boot(config: &BootConfig) -> Result<(ManagedServers, String), BootError> {
    let backend_port = backend_port(&config.root, &config.data_dir);
    let app_url = format!("http://127.0.0.1:{backend_port}");
    let frontend_out = config
        .root
        .join("frontend")
        .join("out")
        .join("index.html");

    let on1y_exe = resolve_backend_exe(config)?;

    if !frontend_out.is_file() {
        return Err(BootError::msg(if config.bundled {
            "安装包资源不完整（缺少前端页面）。请重新下载安装包。".to_string()
        } else {
            format!(
                "前端尚未构建（需要 static export）。请在 PowerShell 中运行:\n  powershell -ExecutionPolicy Bypass -File \"{}\"",
                config.root.join("scripts").join("build-frontend.ps1").display()
            )
        }));
    }

    let mut servers = ManagedServers {
        backend: None,
        started_backend: false,
    };

    if is_port_listening(backend_port) {
        log_line(&config.data_dir, "on1y serve already listening");
    } else {
        servers.backend = Some(spawn_backend(
            &on1y_exe,
            &config.root,
            &config.data_dir,
            backend_port,
            config.bundled,
        )?);
        servers.started_backend = true;
        if !wait_http_ok(
            &format!("{app_url}/api/auth/status"),
            Duration::from_secs(180),
        ) {
            servers.stop_started();
            return Err(BootError::msg(if config.bundled {
                format!(
                    "On1y 服务未在 180 秒内就绪: {app_url}\n请查看 {} 下的 on1y-start.log",
                    config.data_dir.display()
                )
            } else {
                format!(
                    "on1y serve 未在 180 秒内就绪: {app_url}\n请检查 conda 环境 on1y 与 data/ 目录权限。"
                )
            }));
        }
    }

    if !wait_http_ok(&app_url, Duration::from_secs(30)) {
        return Err(BootError::msg(format!(
            "工作台页面未就绪: {app_url}"
        )));
    }

    Ok((servers, app_url))
}

fn resolve_backend_exe(config: &BootConfig) -> Result<PathBuf, BootError> {
    if let Some(path) = config.backend_exe.as_ref() {
        if path.is_file() {
            return Ok(path.clone());
        }
    }
    find_on1y_exe_dev()
}

fn spawn_backend(
    on1y_exe: &Path,
    root: &Path,
    data_dir: &Path,
    backend_port: u16,
    bundled: bool,
) -> Result<Child, BootError> {
    let db_path = data_dir.join("on1y.db");
    let (config_dir, env_file) = resolve_user_config_paths(data_dir, root, bundled);
    let feeds_path = config_dir.join("feeds.yaml");

    let mut cmd = Command::new(on1y_exe);
    cmd.arg("serve")
        .current_dir(root)
        .env("ON1Y_ROOT", root)
        .env("ON1Y_DATA_DIR", data_dir)
        .env("ON1Y_DB_PATH", &db_path)
        .env("ON1Y_WEB_PORT", backend_port.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    if bundled {
        cmd.env("ON1Y_ENV_FILE", &env_file);
        if feeds_path.is_file() {
            cmd.env("ON1Y_RSS_CONFIG_PATH", &feeds_path);
        }
    }

    hide_console(&mut cmd);
    cmd.spawn()
        .map_err(|e| BootError::msg(format!("无法启动 on1y serve: {e}\n路径: {}", on1y_exe.display())))
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}

fn stop_child(child: &mut Option<Child>) {
    if let Some(mut proc) = child.take() {
        let _ = proc.kill();
        let _ = proc.wait();
    }
}

fn is_port_listening(port: u16) -> bool {
    TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], port)),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn wait_http_ok(url: &str, timeout: Duration) -> bool {
    let client = match Client::builder().timeout(Duration::from_secs(3)).build() {
        Ok(c) => c,
        Err(_) => return false,
    };
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(resp) = client.get(url).send() {
            let code = resp.status().as_u16();
            if (200..500).contains(&code) {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

pub fn find_on1y_root() -> PathBuf {
    find_dev_root()
}

fn find_dev_root() -> PathBuf {
    if let Ok(root) = std::env::var("ON1Y_ROOT") {
        let path = PathBuf::from(root);
        if is_dev_root(&path) || is_bundled_app_root(&path) {
            return path;
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        if let Some(found) = walk_for_dev_root(&cwd) {
            return found;
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(found) = walk_for_dev_root(parent) {
                return found;
            }
        }
    }

    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn walk_for_dev_root(start: &Path) -> Option<PathBuf> {
    let mut dir = start.to_path_buf();
    for _ in 0..8 {
        if is_dev_root(&dir) {
            return Some(dir);
        }
        if !dir.pop() {
            break;
        }
    }
    None
}

fn is_dev_root(path: &Path) -> bool {
    path.join("on1y").join("cli").join("main.py").is_file()
        && path.join("frontend").join("package.json").is_file()
}

fn is_bundled_app_root(path: &Path) -> bool {
    path.join("frontend").join("out").join("index.html").is_file()
}

fn find_on1y_exe_dev() -> Result<PathBuf, BootError> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(prefix) = std::env::var("CONDA_PREFIX") {
        candidates.push(PathBuf::from(prefix).join("Scripts").join("on1y.exe"));
    }
    if let Ok(home) = std::env::var("USERPROFILE") {
        let home = PathBuf::from(home);
        for base in ["anaconda3", "miniconda3", "Anaconda3"] {
            candidates.push(
                home.join(base)
                    .join("envs")
                    .join("on1y")
                    .join("Scripts")
                    .join("on1y.exe"),
            );
        }
    }
    candidates.push(PathBuf::from(r"D:\anaconda\envs\on1y\Scripts\on1y.exe"));

    for path in candidates {
        if path.is_file() {
            return Ok(path);
        }
    }

    if let Ok(path) = which_on1y_from_path() {
        return Ok(path);
    }

    Err(BootError::msg(
        "找不到 on1y.exe。开发环境请先: conda activate on1y\n\
         发布版请重新安装 On1y 桌面应用。",
    ))
}

fn which_on1y_from_path() -> Result<PathBuf, BootError> {
    let path_var = std::env::var_os("PATH").ok_or_else(|| BootError::msg("PATH 未设置"))?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join("on1y.exe");
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err(BootError::msg("on1y.exe not on PATH"))
}

fn resolve_user_config_paths(data_dir: &Path, app_root: &Path, bundled: bool) -> (PathBuf, PathBuf) {
    let portable = portable_user_base();
    if bundled && data_dir.starts_with(&portable) {
        (
            portable.join("config"),
            portable.join(".env"),
        )
    } else {
        let parent = data_dir.parent().unwrap_or(app_root);
        (parent.join("config"), parent.join(".env"))
    }
}

fn portable_user_base() -> PathBuf {
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        return PathBuf::from(local).join("On1y");
    }
    PathBuf::from(".").join("On1yUser")
}

fn random_secret() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{nanos:x}{nanos:032x}")
}

#[derive(Deserialize)]
struct LaunchPrefs {
    open_browser_on_start: Option<bool>,
    close_window_action: Option<String>,
    data_dir_override: Option<String>,
}

fn read_launch_prefs_at(path: &Path) -> LaunchPrefs {
    let Ok(text) = fs::read_to_string(path) else {
        return LaunchPrefs {
            open_browser_on_start: None,
            close_window_action: None,
            data_dir_override: None,
        };
    };
    serde_json::from_str(&text).unwrap_or(LaunchPrefs {
        open_browser_on_start: None,
        close_window_action: None,
        data_dir_override: None,
    })
}

fn resolve_data_dir_dev(root: &Path) -> PathBuf {
    let default_dir = root.join("data");
    let prefs_path = default_dir.join("app-launch.json");
    let prefs = read_launch_prefs_at(&prefs_path);
    if let Some(raw) = prefs.data_dir_override {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            let path = PathBuf::from(trimmed);
            if path.is_absolute() {
                return path;
            }
            return root.join(path);
        }
    }
    default_dir
}

fn dev_data_dir_if_present() -> Option<PathBuf> {
    if let Ok(root) = std::env::var("ON1Y_ROOT") {
        let path = PathBuf::from(root);
        if is_dev_root(&path) {
            let data = path.join("data");
            if data.join("on1y.db").is_file() {
                return Some(data);
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(dev) = walk_for_dev_root(parent) {
                let data = dev.join("data");
                if data.join("on1y.db").is_file() {
                    return Some(data);
                }
            }
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        if let Some(dev) = walk_for_dev_root(&cwd) {
            let data = dev.join("data");
            if data.join("on1y.db").is_file() {
                return Some(data);
            }
        }
    }
    None
}

pub fn resolve_data_dir_for_prefs(root: &Path, bundled: bool) -> PathBuf {
    if bundled {
        let base = portable_user_base();
        let data_dir = base.join("data");
        let prefs = read_launch_prefs_at(&data_dir.join("app-launch.json"));
        if let Some(raw) = prefs.data_dir_override {
            let trimmed = raw.trim();
            if !trimmed.is_empty() {
                return PathBuf::from(trimmed);
            }
        }
        if let Some(dev_data) = dev_data_dir_if_present() {
            return dev_data;
        }
        return data_dir;
    }
    resolve_data_dir_dev(root)
}

pub fn read_open_window_pref(root: &Path, bundled: bool) -> bool {
    let data_dir = resolve_data_dir_for_prefs(root, bundled);
    read_launch_prefs_at(&data_dir.join("app-launch.json"))
        .open_browser_on_start
        .unwrap_or(true)
}

pub fn read_close_window_action(root: &Path, bundled: bool) -> String {
    let data_dir = resolve_data_dir_for_prefs(root, bundled);
    let action = read_launch_prefs_at(&data_dir.join("app-launch.json"))
        .close_window_action
        .unwrap_or_else(|| "quit".to_string());
    if action == "quit" {
        "quit".to_string()
    } else {
        "hide".to_string()
    }
}

fn log_line(data_dir: &Path, message: &str) {
    let _ = fs::create_dir_all(data_dir);
    let line = format!("desktop: {message}\n");
    let _ = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(data_dir.join("on1y-start.log"))
        .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
}

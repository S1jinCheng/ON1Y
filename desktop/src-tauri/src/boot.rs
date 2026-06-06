use std::fs;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use reqwest::blocking::Client;
use serde::Deserialize;

const DEFAULT_BACKEND_PORT: u16 = 8765;

fn backend_port(root: &Path) -> u16 {
    if let Ok(port_str) = std::env::var("ON1Y_WEB_PORT") {
        if let Ok(port) = port_str.trim().parse::<u16>() {
            return port;
        }
    }
    let env_path = root.join(".env");
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
    DEFAULT_BACKEND_PORT
}

#[derive(Clone)]
pub struct BootConfig {
    pub root: PathBuf,
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

pub fn boot(config: &BootConfig) -> Result<(ManagedServers, String), BootError> {
    let backend_port = backend_port(&config.root);
    let app_url = format!("http://127.0.0.1:{backend_port}");
    let data_dir = config.root.join("data");
    let frontend_out = config.root.join("frontend").join("out").join("index.html");

    let on1y_exe = find_on1y_exe(&config.root)?;

    if !frontend_out.is_file() {
        return Err(BootError::msg(format!(
            "前端尚未构建（需要 static export）。请在 PowerShell 中运行:\n  powershell -ExecutionPolicy Bypass -File \"{}\"",
            config.root.join("scripts").join("build-frontend.ps1").display()
        )));
    }

    let mut servers = ManagedServers {
        backend: None,
        started_backend: false,
    };

    if is_port_listening(backend_port) {
        log_line(&config.root, "on1y serve already listening");
    } else {
        servers.backend = Some(spawn_backend(
            &on1y_exe,
            &config.root,
            &data_dir,
            backend_port,
        )?);
        servers.started_backend = true;
        if !wait_http_ok(
            &format!("{app_url}/api/auth/status"),
            Duration::from_secs(120),
        ) {
            servers.stop_started();
            return Err(BootError::msg(format!(
                "on1y serve 未在 120 秒内就绪: {app_url}\n请检查 conda 环境 on1y 与 data/ 目录权限。"
            )));
        }
    }

    if !wait_http_ok(&app_url, Duration::from_secs(30)) {
        return Err(BootError::msg(format!(
            "工作台页面未就绪: {app_url}\n请重新运行 scripts\\build-frontend.ps1"
        )));
    }

    Ok((servers, app_url))
}

fn spawn_backend(
    on1y_exe: &Path,
    root: &Path,
    data_dir: &Path,
    backend_port: u16,
) -> Result<Child, BootError> {
    let db_path = data_dir.join("on1y.db");
    let mut cmd = Command::new(on1y_exe);
    cmd.arg("serve")
        .current_dir(root)
        .env("ON1Y_ROOT", root)
        .env("ON1Y_DATA_DIR", data_dir)
        .env("ON1Y_DB_PATH", &db_path)
        .env("ON1Y_WEB_PORT", backend_port.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
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
    if let Ok(root) = std::env::var("ON1Y_ROOT") {
        let path = PathBuf::from(root);
        if is_on1y_root(&path) {
            return path;
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        if let Some(found) = walk_for_root(&cwd) {
            return found;
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(found) = walk_for_root(parent) {
                return found;
            }
        }
    }

    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn walk_for_root(start: &Path) -> Option<PathBuf> {
    let mut dir = start.to_path_buf();
    for _ in 0..8 {
        if is_on1y_root(&dir) {
            return Some(dir);
        }
        if !dir.pop() {
            break;
        }
    }
    None
}

fn is_on1y_root(path: &Path) -> bool {
    path.join("on1y").join("cli").join("main.py").is_file()
        && path.join("frontend").join("package.json").is_file()
}

pub fn find_on1y_exe(_root: &Path) -> Result<PathBuf, BootError> {
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
        "找不到 on1y.exe。请先执行: conda activate on1y\n\
         或设置环境变量 ON1Y_ROOT 指向 D:\\On1y",
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

#[derive(Deserialize)]
struct LaunchPrefs {
    open_browser_on_start: Option<bool>,
}

pub fn read_open_window_pref(root: &Path) -> bool {
    let path = root.join("data").join("app-launch.json");
    let Ok(text) = fs::read_to_string(path) else {
        return true;
    };
    let Ok(prefs) = serde_json::from_str::<LaunchPrefs>(&text) else {
        return true;
    };
    prefs.open_browser_on_start.unwrap_or(true)
}

fn log_line(root: &Path, message: &str) {
    let log_dir = root.join("data");
    let _ = fs::create_dir_all(&log_dir);
    let line = format!("desktop: {message}\n");
    let _ = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("on1y-start.log"))
        .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
}

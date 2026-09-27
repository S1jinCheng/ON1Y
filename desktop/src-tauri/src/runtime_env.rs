//! Repair packaged authentication configuration without touching account data.

use std::fs;
use std::io::Write;
use std::path::Path;

const AUTH_KEY: &str = "ON1Y_AUTH_SECRET_KEY";

fn configured_value<'a>(body: &'a str, key: &str) -> Option<&'a str> {
    body.lines()
        .filter_map(|line| {
            let line = line.trim().trim_start_matches('\u{feff}');
            let line = line.strip_prefix("export ").unwrap_or(line).trim_start();
            if line.starts_with('#') {
                return None;
            }
            let (name, value) = line.split_once('=')?;
            if name.trim() != key {
                return None;
            }
            let value = value.trim();
            if let Some(rest) = value.strip_prefix('"') {
                return Some(rest.split('"').next().unwrap_or(""));
            }
            if let Some(rest) = value.strip_prefix('\'') {
                return Some(rest.split('\'').next().unwrap_or(""));
            }
            Some(value.split(" #").next().unwrap_or("").trim())
        })
        .last()
}

fn usable_secret(value: &str) -> bool {
    !matches!(
        value.trim(),
        "" | "change-me-in-production" | "change-to-a-long-random-string"
    )
}

pub fn random_secret() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).map_err(|_| "无法从操作系统生成安全的登录密钥".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn repaired_body(original: &str) -> Result<Option<String>, String> {
    if configured_value(original, AUTH_KEY).is_some_and(usable_secret) {
        return Ok(None);
    }
    let secret = random_secret()?;
    // dotenv uses the last active assignment. Appending preserves comments,
    // unrelated configuration and existing authentication/registration settings.
    Ok(Some(format!("{original}\n{AUTH_KEY}={secret}\n")))
}

pub fn ensure_runtime_env(env_path: &Path, example: &Path) -> Result<(), String> {
    let exists = env_path.exists();
    let original = if exists {
        fs::read_to_string(env_path).map_err(|_| "无法读取本机 On1y 配置".to_string())?
    } else if example.is_file() {
        fs::read_to_string(example).map_err(|_| "无法读取 On1y 配置模板".to_string())?
    } else {
        String::new()
    };
    // A template is never allowed to supply a shared signing key to all installs.
    let replacement = if exists {
        repaired_body(&original)?
    } else {
        Some(format!("{original}\n{AUTH_KEY}={}\n", random_secret()?))
    };
    let Some(body) = replacement else {
        return Ok(());
    };
    let parent = env_path.parent().ok_or("On1y 配置路径无效")?;
    if exists {
        let backup = env_path.with_file_name(".env.before-auth-fix");
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(backup) {
            Ok(mut file) => {
                file.write_all(original.as_bytes())
                    .and_then(|_| file.sync_all())
                    .map_err(|_| "无法备份 On1y 配置，已停止修复".to_string())?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(_) => return Err("无法备份 On1y 配置，已停止修复".to_string()),
        }
    }
    // tempfile uses private permissions on Unix and atomic replacement on both
    // Windows and macOS. A failed write must not truncate the original .env.
    let mut staged = tempfile::NamedTempFile::new_in(parent)
        .map_err(|_| "无法创建 On1y 临时配置".to_string())?;
    staged
        .write_all(body.as_bytes())
        .and_then(|_| staged.as_file().sync_all())
        .map_err(|_| "无法写入 On1y 配置".to_string())?;
    staged
        .persist(env_path)
        .map_err(|_| "无法保存 On1y 配置".to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn comments_are_not_configuration() {
        let body = "# ON1Y_AUTH_SECRET_KEY=example\nON1Y_AUTH_REQUIRED=true\n";
        let repaired = repaired_body(body).unwrap().unwrap();
        let secret = configured_value(&repaired, AUTH_KEY).unwrap();
        assert_eq!(secret.len(), 64);
        assert!(secret.bytes().all(|b| b.is_ascii_hexdigit()));
        assert_eq!(
            configured_value(&repaired, "ON1Y_AUTH_REQUIRED"),
            Some("true")
        );
        assert!(repaired_body(&repaired).unwrap().is_none());
    }

    #[test]
    fn empty_and_placeholder_values_are_repaired() {
        for value in [
            "",
            "''",
            "\"\"",
            "change-me-in-production",
            "'change-to-a-long-random-string' # template",
        ] {
            let body = format!("{AUTH_KEY}={value}\n");
            assert!(repaired_body(&body).unwrap().is_some());
        }
    }

    #[test]
    fn existing_secrets_and_other_settings_are_preserved() {
        for value in [
            "my-existing-key",
            "'key#with-hash'",
            "\"existing value\" # note",
        ] {
            let body = format!("# {AUTH_KEY}=ignored\nexport {AUTH_KEY} = {value}\nOTHER=keep\n");
            assert!(repaired_body(&body).unwrap().is_none());
        }
        let body = format!("{AUTH_KEY}=valid\n{AUTH_KEY}=\"\"\n");
        assert!(repaired_body(&body).unwrap().is_some());
    }

    #[test]
    fn existing_install_is_backed_up_and_repaired_once() {
        let dir = tempfile::tempdir().unwrap();
        let env = dir.path().join(".env");
        let original = "ON1Y_AUTH_REQUIRED=true\n# ON1Y_AUTH_SECRET_KEY=example\nOTHER=keep\n";
        fs::write(&env, original).unwrap();
        ensure_runtime_env(&env, &dir.path().join("missing.example")).unwrap();
        let repaired = fs::read_to_string(&env).unwrap();
        assert_eq!(
            fs::read_to_string(dir.path().join(".env.before-auth-fix")).unwrap(),
            original
        );
        assert!(repaired.starts_with(original));
        ensure_runtime_env(&env, &dir.path().join("missing.example")).unwrap();
        assert_eq!(fs::read_to_string(&env).unwrap(), repaired);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&env).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }

    #[test]
    fn fresh_install_gets_unique_secret_even_when_template_has_one() {
        let dir = tempfile::tempdir().unwrap();
        let example = dir.path().join(".env.example");
        fs::write(&example, "ON1Y_AUTH_SECRET_KEY=shared-template-key\n").unwrap();
        let env = dir.path().join(".env");
        ensure_runtime_env(&env, &example).unwrap();
        let body = fs::read_to_string(&env).unwrap();
        assert_ne!(
            configured_value(&body, AUTH_KEY),
            Some("shared-template-key")
        );
        assert!(!dir.path().join(".env.before-auth-fix").exists());
        assert_ne!(random_secret().unwrap(), random_secret().unwrap());
    }

    #[test]
    fn write_failures_are_not_silently_ignored() {
        let dir = tempfile::tempdir().unwrap();
        let env = dir.path().join("missing/.env");
        assert!(ensure_runtime_env(&env, &dir.path().join("missing.example")).is_err());
        assert!(!env.exists());
    }
}

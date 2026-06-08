# 发布说明

On1y 对外只发布 **一个正式版本**：Windows 安装程序 `On1y_<版本>_x64-setup.exe`。

用户双击安装后，从开始菜单启动 **On1y** 即可使用，无需安装 Python、Conda 或 Node.js。

---

## 发布产物


| 文件                                                              | 说明                              |
| --------------------------------------------------------------- | ------------------------------- |
| `desktop/src-tauri/target/release/bundle/nsis/On1y_*-setup.exe` | **唯一对外分发物**，上传至 GitHub Releases |


安装后用户数据在 `%LOCALAPPDATA%\On1y\`（数据库、Cookie、配置），与程序目录分离。

构建过程中会在 `dist/portable/` 生成中间资源（前端静态文件 + PyInstaller 后端），供 Tauri 打进安装包，**不单独分发**。

---

## 构建环境（维护者）

- Windows 10/11
- Conda 环境 `on1y`（Python 3.11+）
- Node.js 18+
- Rust + WebView2
- 首次：`pip install -e ".[dev]"`（含 PyInstaller）

---

## 一键打包

```powershell
cd D:\On1y
conda activate on1y

# 组装资源 + 构建 NSIS 安装包
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

或分步执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package-release.ps1
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
```

完成后安装包位于：

```
desktop\src-tauri\target\release\bundle\nsis\On1y_0.1.0_x64-setup.exe
```

可复制到 `dist\` 便于上传：

```powershell
Copy-Item desktop\src-tauri\target\release\bundle\nsis\On1y_0.1.0_x64-setup.exe dist\
```

---

## 发布到 GitHub Releases

1. 确认版本号一致：`pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/tauri.conf.json`、`desktop/src-tauri/Cargo.toml`
2. 提交并推送源码，打标签：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

1. 打开 [GitHub Releases](https://github.com/S1jinCheng/ON1Y/releases/new)
2. 选择标签 `v0.1.0`，上传 `On1y_0.1.0_x64-setup.exe`
3. 正文可参考 [RELEASE_NOTES_v0.1.0.md](RELEASE_NOTES_v0.1.0.md)

---

## 用户安装后

1. 从开始菜单或桌面快捷方式打开 **On1y**
2. 注册 / 登录本机账号
3. 按 [COOKIES.md](COOKIES.md) 导入各平台 Cookie
4. 如需访问 YouTube 等，按 [PROXY.md](PROXY.md) 配置代理
5. 在设置页完成首次订阅同步

---

## 开发版 vs 安装版


|      | 开发（源码）                         | 正式安装版                  |
| ---- | ------------------------------ | ---------------------- |
| 启动方式 | `on1y serve` 或开发树 `On1y.exe`   | 安装后的开始菜单 **On1y**      |
| 后端   | Conda 环境 `on1y`                | 安装包内捆绑的 `on1y.exe`     |
| 前端   | `frontend/out` 或 `npm run dev` | 安装包内捆绑的静态资源            |
| 数据   | 默认 `D:\On1y\data`（开发）          | `%LOCALAPPDATA%\On1y\` |


日常开发仍用 `on1y serve`，发布流程不影响源码开发。


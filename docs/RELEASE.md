# On1y 发布打包

面向「用户下载安装即可用」，不依赖 Conda / 源码环境。

## 产物

| 文件 | 说明 |
|------|------|
| `dist/On1y-portable-0.1.0-win64.zip` | 便携资源包（后端 + 前端静态文件），供调试 |
| `desktop/src-tauri/target/release/bundle/nsis/On1y_*.exe` | **推荐**：Windows 安装程序，双击安装后从开始菜单启动 On1y |
| `desktop/src-tauri/target/release/On1y.exe` | 未打包的桌面壳（需已执行 `package-release.ps1`） |

安装后用户数据默认在：`%LOCALAPPDATA%\On1y\`（数据库、Cookie、配置），与程序目录分离。

## 构建环境（仅维护者需要）

- Windows 10/11
- Conda 环境 `on1y`（Python 3.11）
- Node.js 18+（构建前端）
- Rust + WebView2（构建 Tauri）
- 首次：`pip install -e ".[dev]"`（含 PyInstaller）

## 一键打包

```powershell
cd D:\On1y
conda activate on1y

# 1. 组装便携资源（PyInstaller 后端 + frontend/out + sql）
powershell -ExecutionPolicy Bypass -File scripts\package-release.ps1

# 2. 构建 NSIS 安装包（含上述资源）
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
```

完成后将 `On1y_*-setup.exe` 分发给用户。

## 用户安装后

1. 运行安装程序，从开始菜单或桌面打开 **On1y**
2. 首次启动自动创建 `%LOCALAPPDATA%\On1y\.env` 与数据目录
3. 在网页设置中上传 **B 站 / YouTube / 知乎** Cookie（或使用浏览器扩展导出后上传）
4. 注册/登录账号，按引导完成冷启动同步

**说明**

- 无需安装 Python、Conda、Node.js
- 知乎正文提取需本机已安装 Playwright Chromium；首次使用知乎可在设置页查看提示，或维护者预装：在打包机执行 `playwright install chromium` 后将浏览器缓存一并分发（可选，体积较大）
- YouTube 访问可能需要用户在设置或 `.env` 中配置代理

## 开发机 vs 发布版

| | 开发 | 发布安装包 |
|--|------|------------|
| 后端 | `conda` 下的 `on1y.exe` | 捆绑的 `resources/backend/on1y/on1y.exe` |
| 前端 | `frontend/out` 或 `npm run dev` | 捆绑在 `resources/app/frontend/out` |
| 数据 | `D:\On1y\data` | `%LOCALAPPDATA%\On1y\data` |

开发日常仍用 `on1y serve`；发布流程不影响源码开发。

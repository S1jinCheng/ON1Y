<div align="center">

<!-- 可选：在 Canva 做 1280×320 横幅 → docs/images/banner.png，然后取消下一行注释并删掉 Logo -->
<!-- <img src="docs/images/banner.png" alt="On1y" width="100%" /> -->
<img src="frontend/public/on1y-logo.png" alt="On1y" width="96" />

# On1y

**把分散在各平台的订阅与收藏，收进一座只属于你自己的本地知识库。**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/S1jinCheng/ON1Y?label=release)](https://github.com/S1jinCheng/ON1Y/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows)](https://github.com/S1jinCheng/ON1Y/releases/latest)

[下载安装包](https://github.com/S1jinCheng/ON1Y/releases/latest) · [快速开始](#安装与启动) · [演示](#演示) · [文档](docs/)

</div>

---

## 描述

你在 B 站、YouTube、知乎里关注了很多创作者，收藏了很多内容——但它们散落在各个 App 的信息流里，很难回顾、很难搜索、换一台电脑就接不上。

**On1y** 做一件事：把这些你已经「关注」和「收藏」的内容，自动汇聚到**本机**，提取字幕与正文，可选生成 AI 摘要，再用全文搜索和主题整理把它们变成一座**个人知识库**。

- 数据在本地，不上传云端
- 支持多账号、备份迁移
- 提供 Windows 桌面安装版，开箱即用

<!-- 在这里补充你的愿景与个人叙事（1～3 段） -->

> On1y 想做的，不是再造一个信息流，而是让你**已经消费过的内容**真正留下来、找得到、用得上。

### 能做什么

| | |
|:---:|:---|
| 📥 **采集** | B 站关注动态 · YouTube 频道 · 知乎关注；收藏夹与稍后观看 |
| 📄 **提取** | 视频字幕 · 知乎正文 · 文章正文 |
| ✨ **蒸馏** | LLM 摘要、要点、自动标签（可选） |
| 🔍 **检索** | 本地 FTS 全文搜索，标题 / 正文 / 摘要 |
| 📊 **整理** | 按创作者、标签浏览；笔记、收藏、相关推荐 |
| 📰 **扩展** | 知乎热榜、《经济学人》周刊、Kindle 推送 |
| 💾 **迁移** | 导出 `.on1y.zip`，换机可恢复 |

<!-- 工作台大图：截图保存为 docs/images/workbench.png 后取消注释
<div align="center">
<img src="docs/images/workbench.png" alt="On1y 工作台" width="90%" />
</div>
-->

---

## 演示

On1y 是**本地优先**应用，没有公网在线 Demo（数据与 Cookie 都在你的电脑上）。推荐用**录屏视频**展示安装与使用流程。

### 演示视频

<!-- 方式 A：录好后把 mp4 拖到 GitHub Issue 评论上传，复制链接替换下方 src -->
<!-- 方式 B：上传 B 站 / YouTube，用封面图链到外链（见 demo-poster 示例） -->

https://github.com/user-attachments/assets/PLACEHOLDER

*↑ 将 `PLACEHOLDER` 替换为你的视频链接。录制指南见 [docs/images/README.md](docs/images/README.md)。*

<!-- 方式 B 示例（二选一，删掉不用的）：
<div align="center">
<a href="https://www.bilibili.com/video/BVxxxx">
  <img src="docs/images/demo-poster.png" alt="观看演示视频" width="80%" />
</a>
<p>点击观看 B 站演示</p>
</div>
-->

**建议录制内容（约 90 秒～3 分钟）：**

1. 安装并打开 On1y → 注册登录  
2. 设置页导入 Cookie（B 站 / YouTube / 知乎）  
3. 触发一次订阅同步，展示新内容入库  
4. 全文搜索 + 打开一条内容的摘要/正文  

### 截图

将截图放入 `docs/images/` 后取消下方注释：

<!--
| 工作台 | 设置与同步 |
|:---:|:---:|
| <img src="docs/images/workbench.png" width="400" alt="工作台" /> | <img src="docs/images/settings.png" width="400" alt="设置" /> |
-->

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **桌面壳** | [Tauri 2](https://tauri.app/) · WebView2 |
| **前端** | [Next.js 14](https://nextjs.org/) · React 18 · TypeScript · Tailwind CSS · Zustand |
| **后端** | [FastAPI](https://fastapi.tiangolo.com/) · Uvicorn · Pydantic |
| **存储** | SQLite · FTS5 全文索引 |
| **采集** | B 站 API · RSS / feedparser · yt-dlp |
| **提取** | Playwright（知乎等）· Jina Reader · BeautifulSoup |
| **AI** | 可配置 OpenAI 兼容 API（摘要 / 标签） |
| **打包** | PyInstaller · NSIS 安装程序 |

```
订阅源 / 收藏 / 热榜
    → 入队 → Worker（元数据快入）
    → 字幕 Worker（yt-dlp）→ 正文提取
    → SQLite + FTS5
    → FastAPI ←→ Next.js 工作台
```

---

## 需要注意的坑

这些是开发和日常使用里最容易踩的点：

### 1. Cookie 和代理是两回事

- **Cookie**：证明「你是 logged-in 用户」，在设置页用 [Cookie-Editor](docs/COOKIES.md) 导出 JSON 导入。  
- **代理**：解决「能不能连上外网」。浏览器上不去 YouTube，On1y 也上不去。见 [docs/PROXY.md](docs/PROXY.md)。

YouTube **两个都要配**。只配代理、Cookie 是游客态，仍然拉不到订阅。

### 2. YouTube Cookie 经常是「假的登录」

导出时必须在 **youtube.com 已登录** 页面操作。若 JSON 只有十来条访客 Cookie，同步会失败——需要重新登录后再导出。

### 3. 国内平台与国外平台策略不同

| 平台 | 通常需要 |
|------|----------|
| 哔哩哔哩、知乎 | 有效 Cookie |
| YouTube、GitHub（经济学人） | Cookie + 代理 |

### 4. 知乎可能触发「安全验证」

知乎正文走 Playwright。若频繁报安全验证，先在浏览器正常浏览知乎，再重新导出 Cookie；安装版用户需本机有 Chromium 环境（设置页有说明）。

### 5. 改前端 ≠ 桌面安装包自动更新

只跑 `npm run build` 只会更新 `frontend/out`。**正式安装包**需要：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

### 6. 开发版与安装版数据目录不同

| 环境 | 数据位置 |
|------|----------|
| 源码开发 | `data/`（项目目录下） |
| 正式安装版 | `%LOCALAPPDATA%\On1y\` |

换环境请用设置里的 **知识库备份** 导出 `.on1y.zip`。

### 7. B 站订阅默认走「关注动态」

默认从关注动态拉视频，**不要**轻易改成 per-UP `space/arc/search`，容易触发 412 限流。

---

## 安装与启动

### 用户：Windows 安装包（推荐）

1. 从 [GitHub Releases](https://github.com/S1jinCheng/ON1Y/releases/latest) 下载 `On1y_*-setup.exe`
2. 双击安装，从开始菜单打开 **On1y**
3. 注册 / 登录 → 按 [docs/COOKIES.md](docs/COOKIES.md) 导入 Cookie
4. 需要 YouTube 时按 [docs/PROXY.md](docs/PROXY.md) 配置代理
5. 设置页选择订阅平台与起始日期，执行首次同步

系统要求：Windows 10/11 x64 · [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)

### 开发者：从源码运行

```powershell
conda create -n on1y python=3.11 -y
conda activate on1y
git clone https://github.com/S1jinCheng/ON1Y.git
cd ON1Y
pip install -e ".[dev]"
copy .env.example .env
on1y init
on1y serve
```

浏览器打开 **http://127.0.0.1:8765**。

前端热更新（另开终端）：

```powershell
cd frontend
npm install
npm run dev
```

构建正式安装包见 [docs/RELEASE.md](docs/RELEASE.md)。

### 常用命令

| 命令 | 说明 |
|------|------|
| `on1y serve` | 启动后端与工作台 |
| `on1y subscriptions --platform all --ingest` | 同步订阅并入库 |
| `on1y cookies status` | 检查 Cookie 状态 |
| `on1y search -q "关键词"` | 全文搜索 |
| `pytest -q` | 运行测试 |

---

## 如何贡献

欢迎 Issue 与 Pull Request。

1. **Fork** 本仓库，创建分支 `feat/your-feature`
2. 开发环境见上方「从源码运行」；改动后运行 `ruff check on1y tests` 与 `pytest -q`
3. 提交 PR 时请简要说明改动动机与测试方式
4. 不要提交 `.env`、`data/`、Cookie 等敏感文件



## License

[MIT](LICENSE) · 仓库 [github.com/S1jinCheng/ON1Y](https://github.com/S1jinCheng/ON1Y)

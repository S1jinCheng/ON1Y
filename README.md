# On1y

**个人知识库工作台** — 把 B 站、YouTube、知乎等订阅与收藏里的内容收进本地，自动提取正文/字幕，生成 AI 摘要，支持全文搜索与主题整理。

数据保存在本机，支持多账号、备份迁移与 Windows 桌面版。

---

## 用户使用指南

### On1y 能帮你做什么

- **自动跟进订阅**：B 站关注动态、YouTube 频道、知乎关注（RSS），新内容入库后自动拉字幕/正文
- **同步收藏夹**：B 站 / 知乎收藏、YouTube 稍后观看与点赞列表
- **热榜与专栏**：知乎热榜、《经济学人》周刊（与日常关注分开管理）
- **AI 阅读助手**：为每条内容生成摘要、要点和标签，可归类到主题
- **本地知识库**：全文搜索、按创作者浏览、收藏、笔记、相关推荐
- **换机不丢数据**：导出 `.on1y.zip` 备份，可在另一台电脑或另一个账号下恢复

### 你需要准备什么

| 项目 | 说明 |
|------|------|
| Windows 电脑 | 当前主要面向 Windows 使用（也支持命令行在其他系统跑后端） |
| Python 环境 | 安装 Conda，创建 `on1y` 环境（见下方「首次安装」） |
| 平台登录态 | 至少配置一个平台的 Cookie（B 站 / YouTube / 知乎），才能同步订阅 |
| LLM API Key（可选） | 需要 AI 摘要时在设置里填写；不配置也能先采集和阅读原文 |
| 浏览器 | 访问工作台：`http://127.0.0.1:8765` |

### 首次安装（约 10 分钟）

```powershell
# 1. 进入项目目录
cd D:\On1y

# 2. 安装 Python 依赖
conda create -n on1y python=3.11 -y
conda activate on1y
pip install -e .

# 3. 复制配置文件
copy .env.example .env
copy config\feeds.yaml.example config\feeds.yaml

# 4. 初始化
on1y init
```

编辑 `.env`，至少设置 **`ON1Y_AUTH_SECRET_KEY`**（任意长随机字符串，用于登录）。首次启动时按提示创建管理员账号。

### 开始使用（推荐流程）

**1. 导出 Cookie**（在已登录 B 站 / YouTube / 知乎的浏览器里执行）：

```powershell
python scripts\export_cookies.py bilibili
python scripts\export_cookies.py youtube
python scripts\export_cookies.py zhihu
on1y cookies status
```

详细步骤见 [docs/COOKIES.md](docs/COOKIES.md)。

**2. 启动服务并打开网页：**

```powershell
on1y serve
```

浏览器访问 **http://127.0.0.1:8765**，登录后进入工作台。

**3. 在网页里完成配置（设置页）：**

- 上传或确认各平台 Cookie
- 设置订阅起始日期（只同步该日期之后的内容）
- （可选）填写 LLM API，开启自动摘要
- （可选）配置 Kindle 邮箱、经济学人自动推送

**4. 拉取内容：**

- 跟随首次引导做 **冷启动全量同步**（订阅 + 收藏 + 入库），或
- 在设置里手动触发同步；也可在终端执行：

```powershell
on1y subscriptions --platform all --ingest
```

之后日常使用：**打开 `on1y serve` → 网页阅读、搜索、整理即可**。若开启 `ON1Y_AUTO_SYNC_ENABLED=true`，服务运行时会后台定期同步新内容。

### Windows 桌面版（可选）

不想每次开终端时，可构建 Tauri 桌面壳（托盘图标、一键启动），见 [desktop/README.md](desktop/README.md)。

### 常见问题

| 现象 | 处理 |
|------|------|
| 网页打不开 | 确认 `on1y serve` 在运行；端口默认 `8765` |
| 订阅没有新内容 | 检查 `on1y cookies status`；B 站需有效登录 Cookie |
| 没有 AI 摘要 | 在设置中配置 LLM API Key |
| YouTube 拉取失败 | 在 `.env` 配置代理 `ON1Y_YTDLP_PROXY` |
| 换电脑 | 设置 → 知识库备份 → 导出 `.on1y.zip`，新环境导入 |

更多界面说明：[docs/WEB.md](docs/WEB.md)

---

## 开发者指南

面向参与维护、二次开发或部署的读者。实现细节见 `docs/` 与各模块内代码。

### 架构概览

```
采集源（订阅 API / RSS / 收藏 / 热榜 / 手动 URL）
    → pending_urls（按用户排队）
    → Worker（视频：元数据快入 → pending_subtitles）
    → 字幕 Worker（YouTube / B 站，yt-dlp）
    → 正文提取（知乎 Playwright、文章 Jina 等）
    → raw_items（SQLite，user_id 隔离）
    → LLM 蒸馏（摘要 / 标签 / 主题）
    → FTS5 索引 → FastAPI + Next.js 工作台
```

**设计要点**：提取层与存储通过 Port 抽象；平台提取器可插拔注册；视频采用「先入库、后字幕」两阶段，避免阻塞订阅轮询。

### 仓库结构

| 路径 | 职责 |
|------|------|
| `on1y/cli/` | CLI 入口 |
| `on1y/web/` | FastAPI 服务与 REST API |
| `on1y/adapters/` | SQLite 存储实现 |
| `on1y/ingestion/` | RSS、B 站 API、入队 |
| `on1y/subscriptions/` | 多平台订阅编排 |
| `on1y/extract/` | 各平台提取器 |
| `on1y/pipeline/` | Worker、字幕、蒸馏管道 |
| `on1y/search/` | FTS 全文检索 |
| `on1y/sync/` | 冷启动全量同步 |
| `on1y/user/` | 多用户账号、profile、备份 |
| `frontend/` | Next.js 工作台（静态导出至 `frontend/out/`） |
| `desktop/` | Tauri 桌面壳 |
| `data/` | 运行时数据（不进 Git） |

### 环境与安装

```powershell
conda activate on1y
cd D:\On1y
pip install -e ".[dev]"
playwright install chromium   # 知乎等需要时
```

- Python **3.11+**，环境变量前缀 **`ON1Y_`**（见 `.env.example`）
- 前端构建需 **Node.js 18+**；桌面版另需 **Rust + WebView2**

```powershell
# 前端静态资源（on1y serve 读取 frontend/out/）
powershell -ExecutionPolicy Bypass -File scripts\build-frontend.ps1

# 桌面安装包
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
```

### 常用开发命令

| 类别 | 命令 |
|------|------|
| 服务 | `on1y serve` |
| 订阅 | `on1y subscriptions --platform all --ingest` |
| 收藏 / 热榜 | `on1y collections sync` · `on1y hotlist sync` |
| 队列 | `on1y worker --once` · `on1y subtitles --limit N` · `on1y catchup` |
| 管道 | `on1y pipeline youtube` · `on1y pipeline zhihu` |
| 蒸馏 | `on1y distill --limit N` |
| 搜索 | `on1y search -q "…"` · `on1y search rebuild` |
| 数据 | `on1y archive export` · `on1y archive import` |
| 质量 | `ruff check on1y tests` · `pytest -q` |

完整子命令：`on1y --help`。

### 数据与多用户

- 主库：`data/on1y.db`（schema 含 `users`、`raw_items.user_id`、FTS）
- 每用户目录：`data/users/<id>/`（cookies、llm_settings、subscription_settings、economist 缓存等）
- 敏感文件：`.env`、`data/`、Cookie **勿提交 Git**

### 延伸阅读

| 文档 | 内容 |
|------|------|
| [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) | 协作者速览、历史决策 |
| [docs/COOKIES.md](docs/COOKIES.md) | Cookie 导出与各平台说明 |
| [docs/WEB.md](docs/WEB.md) | Web API 与前端架构 |
| [docs/RSS.md](docs/RSS.md) | RSSHub、feeds.yaml |
| [docs/YOUTUBE_PIPELINE.md](docs/YOUTUBE_PIPELINE.md) | 视频两阶段管道 |
| [docs/ZHIHU_PIPELINE.md](docs/ZHIHU_PIPELINE.md) | 知乎 Playwright 管道 |
| [docs/PHASE2.md](docs/PHASE2.md) | LLM 蒸馏与分类 |
| [docs/INGEST_PERFORMANCE.md](docs/INGEST_PERFORMANCE.md) | 入库性能与限流 |

### License

MIT · 仓库：[github.com/S1jinCheng/ON1Y](https://github.com/S1jinCheng/ON1Y)

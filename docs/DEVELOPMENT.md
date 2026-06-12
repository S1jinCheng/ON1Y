# 开发指南

面向从源码参与 On1y 开发的贡献者与维护者。

## 环境

- **Python**：3.11+，推荐 Conda 环境 `on1y`
- **Node.js**：18+（前端）
- **Rust + WebView2**：仅构建桌面安装包时需要
- **配置**：仓库根目录 `.env`（从 `.env.example` 复制，勿提交 Git）
- **数据**：`data/`（SQLite、Cookie、订阅设置，勿提交 Git）

## 日常命令

```powershell
conda activate on1y
cd <repo-root>
on1y serve                          # http://127.0.0.1:8765
on1y cookies status
on1y subscriptions --platform all --ingest   # bilibili + youtube/zhihu RSS
on1y hotlist sync                            # 知乎热榜（独立于 zhihu 关注）
on1y search -q "关键词"
on1y search rebuild
```

前端（另开终端）：

```powershell
cd frontend
npm run dev
```

## 架构概览

个人知识库：**采集 → 提取正文/字幕 → LLM 摘要分类 → 全文检索 → Web 工作台**

| 模块 | 路径 |
|------|------|
| CLI / 服务 | `on1y/cli/main.py`, `on1y/web/app.py` |
| 存储 | `on1y/adapters/sqlite_storage.py`, `data/on1y.db` |
| 订阅编排 | `on1y/subscriptions/`（B 站 API + YT/知乎 RSS + sync_job） |
| B 站订阅 | `on1y/ingestion/bilibili_subscriptions.py` |
| 全文搜索 | `on1y/search/fts.py`（FTS5 trigram + BM25，短词 LIKE 兜底） |
| LLM 摘要 | `on1y/distill/` |
| 浏览器爬取 | `on1y/browser/`（Playwright，优先系统 Chrome/Edge） |
| 前端 | `frontend/` Next.js 工作台 |

## 关键行为（勿随意回退）

1. **B 站 UP 订阅**：默认 `bilibili_up_poll_mode=dynamic`（关注动态 `type=video`），跳过图文/专栏/广告；避免 per-UP `space/arc/search`（易 412 限流）。
2. **FTS 搜索**：`knowledge_fts` 索引；入库/摘要/标签变更自动更新；前端搜索 300ms 防抖 + 高亮。
3. **LLM 摘要**：`auto_distill_after_subtitles=True`；`/api/distill/backfill` 批量补摘要。
4. **Cookie**：`data/cookies/*.json`（各平台独立文件）。
5. **统一订阅**：`on1y subscriptions --platform {bilibili|youtube|zhihu|all}`；`zhihu` **不含**热榜；`sync_since` 三平台均生效。
6. **可选定时**：`ON1Y_AUTO_SYNC_ENABLED=true` 时 `on1y serve` 后台周期同步。

## 开发约定

- 最小改动 diff；匹配现有代码风格
- B 站订阅默认保持 **enabled**
- Windows 上 Playwright 用系统 Chrome/Edge；Cookie 导出见 `scripts/export_cookies.py`
- 不要提交 `.env`、LLM API Key、Cookie、`data/` 目录

## 测试与检查

```powershell
pytest -q
ruff check on1y tests
```

## 打包发布

见 [RELEASE.md](RELEASE.md)。

## 常见问题

| 现象 | 处理 |
|------|------|
| 8765 端口占用 | `netstat -ano \| findstr :8765` → `taskkill /PID <pid> /F` |
| Cookie / 代理 | [COOKIES.md](COOKIES.md)、[PROXY.md](PROXY.md) |

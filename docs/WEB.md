# Web 控制台

本地 Web 能力分为两层：

- `on1y serve`：FastAPI 后端（旧静态页仍可用）
- `frontend/`：Next.js 14 三栏前端（follow 风格，标签树 + 信息流 + AI 摘要）

## 启动

```bash
cd ~/On1y
source venv/bin/activate
pip install -e .   # 含 fastapi、uvicorn

on1y serve
# 浏览器打开 http://127.0.0.1:8765/
```

可选参数：

```bash
on1y serve --host 0.0.0.0 --port 8765
```

环境变量：`ON1Y_WEB_HOST`、`ON1Y_WEB_PORT`。

## Next.js 前端（推荐）

```bash
cd ~/On1y/frontend
npm install
NEXT_PUBLIC_ON1Y_API_BASE=http://127.0.0.1:8765 npm run dev
# 打开 http://127.0.0.1:3000
```

核心 API：

- `GET /api/knowledge/tags/tree`：标签树（支持父子层级）
- `GET /api/knowledge/items`：跨源信息流（按标签/平台/来源/关键词筛选）
- `POST /api/knowledge/items/manual`：手动新增内容并可自动蒸馏
- `POST /api/knowledge/items/{raw_id}/tags`：人工改标签
- `POST /api/knowledge/upload`：上传文件并入库（已预留 PDF/Word 接口位）

## 页面功能

| 区域 | 说明 |
|------|------|
| 统计卡片 | 待处理 / 失败 / 已入库 / 订阅数 |
| **RSS 拉取** | 等同 `on1y rss poll`，新链接入队 |
| **处理队列** | 等同 `on1y worker`，可设一次处理条数（默认 3） |
| 手动 URL | 立即提取或仅入队 |
| **订阅** | `config/feeds.yaml` + RSS 游标 |
| **队列** | `pending_urls` 状态 |
| **入库** | `raw_items` 列表，可点「查看」读正文 |
| **LLM 设置** | 页面顶部填写 DeepSeek API Key（存 `data/llm_settings.json`） |
| **蒸馏** | `on1y distill` 同等：摘要、标签、关系 |

## 注意

- 处理队列在浏览器里会**同步等待**（一条 YouTube 常需 15–60 秒），默认一次 3 条，**不适合清大队列**。
- 日常大批量处理请在终端跑 `on1y worker`（持续处理直到队列空）。
- 入库慢、积压多：见 [INGEST_PERFORMANCE.md](./INGEST_PERFORMANCE.md)。
- 页面每 30 秒自动刷新数据。

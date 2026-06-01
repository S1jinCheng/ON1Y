# On1y 项目上下文（人类可读版）

> 供新对话或协作者快速了解项目。Cursor AI 规则见 `.cursor/rules/project-context.mdc`。

## 这是什么

On1y 是个人知识 ingestion 工作台：从 B 站、YouTube、知乎等拉内容，提取正文/字幕，LLM 生成摘要，支持主题/标签分类和全文检索，Web UI 浏览。

## 当前环境（2026-06）

| 项 | 值 |
|----|-----|
| 项目路径 | `D:\On1y` |
| Python | Conda `on1y` |
| 数据库 | `data/on1y.db` |
| GitHub | https://github.com/S1jinCheng/ON1Y |
| 服务地址 | http://127.0.0.1:8765 |

## 快速启动

```powershell
conda activate on1y
cd D:\On1y
on1y serve
```

## 订阅同步（统一入口）

| 平台 | 机制 | 命令 / UI |
|------|------|-----------|
| B 站 UP | API 关注动态 `type=video` | `on1y subscriptions --platform bilibili` |
| YouTube | `feeds.yaml` 中 `yt-*` RSS | `on1y subscriptions --platform youtube` |
| 知乎关注 | `feeds.yaml` 中 `zhihu-*` RSS | `on1y subscriptions --platform zhihu` |
| 全部 | 上三者串联 | `on1y subscriptions --platform all --ingest` |
| 知乎热榜 | 独立热榜 API（**不是**关注订阅） | `on1y hotlist sync` 或 Web「同步知乎热榜」 |

起始日期保存在 `data/subscription_settings.json`（`bilibili_sync_since` / `youtube_sync_since` / `zhihu_sync_since`）。

可选定时（`on1y serve` 后台）：

```env
ON1Y_AUTO_SYNC_ENABLED=true
ON1Y_AUTO_SYNC_INTERVAL_MINUTES=30
ON1Y_AUTO_SYNC_PLATFORM=all
```

Windows 计划任务示例：`scripts/bilibili_subscriptions_tick.ps1`

## 核心功能状态

- **B 站订阅**：动态流模式，Cookie 在 `data/cookies/bilibili.json`
- **全文搜索**：FTS5 trigram
- **LLM 摘要**：入库后自动或批量 backfill
- **Cookie 平台**：YouTube ✅ Bilibili ✅ 知乎 ✅

## 历史决策

1. 从 WSL 迁到 Windows（`D:\On1y`）
2. B 站放弃 per-UP space search，改用动态流 API
3. 搜索是硬性需求，已实现 FTS + 前端实时搜索
4. `subscriptions --platform zhihu` 仅 RSS 关注，不含热榜

## 勿做

- 不要改回 WSL 路径开发
- 不要未经用户同意 disable B 站同步
- 不要 commit `.env`、`data/`、Cookie

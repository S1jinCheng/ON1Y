# RSS 订阅实现说明

On1y 的 RSS 是 **进水管道**：定时拉订阅源 → 新链接进入队列 → Worker 提取正文（与手动 `ingest` 相同）。

```text
config/feeds.yaml
    → on1y rss poll（发现新 URL）
    → pending_urls 队列
    → on1y worker（提取 + raw_items）
```

## 1. 配置文件

```bash
cp config/feeds.yaml.example config/feeds.yaml
```

`config/feeds.yaml` 示例：

```yaml
feeds:
  # GitHub Release（无需登录）
  - url: https://rsshub.app/github/release/microsoft/vscode
    label: vscode-releases
    enabled: true

  # B站 UP 主投稿（RSSHub，抓取仍要靠 B站 Cookie）
  - url: https://rsshub.app/bilibili/user/video/123456
    label: my-bilibili-up
    enabled: true

  # YouTube 频道
  - url: https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxx
    label: my-youtube
    enabled: true

  # 知乎用户动态
  - url: https://rsshub.app/zhihu/people/activities/your-id
    label: zhihu-user
    enabled: false
```

RSSHub 路由见：https://docs.rsshub.app

可自建 RSSHub：`http://127.0.0.1:1200/...`，在 `feeds.yaml` 里把域名换掉即可。

## 2. 常用命令

```bash
source venv/bin/activate

# 查看已配置的订阅
on1y rss feeds

# 查看每个源的游标（上次处理到哪条）
on1y rss status

# 拉取新条目 → 入队（不立刻提取正文）
on1y rss poll

# 一键：拉取 + 处理队列里最多 10 条
on1y rss run --limit 10

# 持续处理队列（另开终端或后台）
on1y worker

# 只看 RSS 进来的内容
on1y list --source rss
```

重置某个订阅的游标（下次 poll 会重新从「最新一条」开始）：

```bash
on1y rss reset vscode-releases
```

## 3. 定时自动跑（cron）

每 30 分钟拉一次订阅，并处理最多 5 条新 URL：

```bash
crontab -e
```

加入（路径按你的用户名修改）：

```cron
*/30 * * * * cd /home/sijin/On1y && ./venv/bin/on1y rss run --limit 5 >> data/rss.log 2>&1
```

或拆成两步：

```cron
*/30 * * * * cd /home/sijin/On1y && ./venv/bin/on1y rss poll >> data/rss.log 2>&1
*/5  * * * * cd /home/sijin/On1y && ./venv/bin/on1y worker --once >> data/worker.log 2>&1
```

## 4. YouTube 关注列表 → RSS

YouTube **没有**「全部关注」的官方聚合 RSS，On1y 的做法是：**每个频道一条**官方 Atom：

`https://www.youtube.com/feeds/videos.xml?channel_id=UC...`

### 自动同步（推荐）

```bash
# 先确保已登录态 Cookie（须含 .google.com 的 __Secure-1PSID 等，见 docs/COOKIES.md）
python scripts/import_cookies.py youtube ~/Downloads/youtube-cookies.json

# 从订阅列表生成 feeds.yaml 里的 yt-* 条目
python scripts/sync_youtube_feeds.py

on1y rss feeds
on1y rss poll
on1y rss run --limit 5
```

若 `sync_youtube_feeds.py` 报 0 个频道：当前 `data/cookies/youtube.json` 可能只是访客 Cookie。请在 **已登录** 的浏览器用 Cookie-Editor 重新导出，或手动维护频道列表：

```bash
cp config/youtube_channels.txt.example config/youtube_channels.txt
# 编辑：每行一个频道链接
python scripts/sync_youtube_feeds.py --from-file config/youtube_channels.txt
```

WSL 访问 YouTube RSS 需与 yt-dlp 相同代理时，在 `.env` 设置 `ON1Y_YTDLP_PROXY`（RSS 拉取会复用该代理）。

---

## 5. 与登录态的关系

| 订阅源内容 | RSS 本身 | 提取正文（Worker） |
|------------|----------|-------------------|
| 公开网页 / GitHub | 通常无需登录 | 无需 Cookie |
| B站 / 知乎 / YouTube 视频 | 只需 RSS 能打开 | **需要** `data/cookies/*.json` |

知乎完整流水线（RSSHub 订阅 + Playwright 限速抓取 + LLM）：见 [ZHIHU_PIPELINE.md](ZHIHU_PIPELINE.md)。

RSS 只负责「发现新 URL」；B 站视频仍依赖你已导出的 `bilibili.json`。

## 6. 首次 poll 行为

每个订阅源 **第一次** `rss poll` 只会入队 **最新 1 条**（避免历史几百条一次性灌爆队列）。  
之后每次只入队比游标更新的条目。

## 7. 故障排查

| 现象 | 处理 |
|------|------|
| `RSS config not found` | `cp config/feeds.yaml.example config/feeds.yaml` |
| `Feed parse error` | 检查 RSSHub 是否可访问；浏览器打开同一 URL 应看到 XML |
| `enqueued: 0` | 没有新内容，或游标已最新；用 `on1y rss status` 查看 |
| 入队了但提取失败 | `on1y worker --once` 看日志；检查对应平台 Cookie |
| RSSHub 限流 | 自建 RSSHub 或降低 cron 频率 |

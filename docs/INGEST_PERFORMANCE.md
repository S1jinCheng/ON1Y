# 入库提速说明

## 为什么感觉慢？

入库 = **队列 worker 逐条**调用各平台提取器，**没有并行**。单条耗时取决于平台：

| 平台 | 典型耗时 | 主要瓶颈 |
|------|----------|----------|
| **YouTube** | 15–60 秒/条 | yt-dlp 经代理访问 Google；拉元数据 + 字幕 |
| **B 站** | 5–30 秒/条 | yt-dlp + Cookie；字幕需登录 |
| **知乎 / 小红书 / X** | 30–90 秒/条 | 每次启动 Chromium + 页面等待 |
| **普通文章** | 5–60+ 秒/条 | Jina Reader（国外）或直连抓取 |

当前队列若积压 **200+ 条 YouTube**，即使每条 30 秒，也要 **约 1.5 小时** 才能清空（且 Web 默认一次只处理 3 条）。

## 立刻能做的（不改代码）

### 1. 用终端持续跑 worker（最重要）

Web「处理队列」会等 HTTP 返回，默认 **3 条/次**，不适合清大队列：

```bash
cd ~/On1y && source venv/bin/activate
on1y worker          # 一直跑，直到队列空
# 或后台
nohup on1y worker >> data/worker.log 2>&1 &
```

### 2. 减少字幕语言（明显缩短 YouTube 时间）

`.env` 里只保留你需要的语言，例如只要中英：

```env
ON1Y_YTDLP_SUB_LANGS=zh-Hans,en
```

默认 8 种语言会多下载、多解析字幕。

### 3. 降低 yt-dlp 重试

失败时少等几次：

```env
ON1Y_YTDLP_RETRIES=1
ON1Y_YTDLP_SOCKET_TIMEOUT=20
```

### 4. 控制 RSS 入队速度

- 日常用 `on1y rss poll`，**不要**频繁 `rss run`（会 poll + worker 叠在一起）。
- 首次订阅已自动只入队「最新 1 条」；若曾重置游标或多次 poll，可能一次入队很多历史视频。

### 5. 确认代理稳定

YouTube 必须走 `ON1Y_YTDLP_PROXY`（WSL 用 Windows 主机 IP，如 `http://172.31.128.1:7897`）。代理不稳会超时并重试，更慢。

## 代码侧已做 / 可选

- **YouTube**：已改为 **单次 yt-dlp**（元数据 + 字幕一次完成），约省一半往返时间。
- **知乎**：`ON1Y_PLAYWRIGHT_SETTLE_MS` 可调小（默认 2000；知乎 extractor 额外 4000ms），可能略快但更容易抓不全。
- **并行 worker**：尚未实现；需要时可加 `on1y worker --jobs 2`（注意 YouTube 429 限流）。

## 查看队列状态

```bash
on1y queue list --status pending --limit 20
on1y stats   # 若有
```

Web 控制台统计卡片也会显示待处理数量。

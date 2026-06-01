# On1y

Personal information routing — **Phase 1: ingestion & extraction** (no LLM).

On1y collects URLs from RSS, manual input, and (later) browser feeds, extracts clean text or subtitles without downloading media, and stores them in a local SQLite archive.

## Architecture

```
Trigger (RSS / manual / API)
    → pending_urls (queue)
    → Worker (video: fast metadata → pending_subtitles)
    → Subtitle worker (YouTube / Bilibili)
    → Extractor registry (Zhihu / Article …)
    → raw_items (SQLite) → distill (LLM tags)
```

Video pipeline (YouTube + Bilibili): [docs/YOUTUBE_PIPELINE.md](docs/YOUTUBE_PIPELINE.md).

Zhihu pipeline (RSSHub + Playwright + LLM): [docs/ZHIHU_PIPELINE.md](docs/ZHIHU_PIPELINE.md).

| Layer | Location | Role |
|-------|----------|------|
| Models | `on1y/models/` | Pydantic contracts between layers |
| Ports | `on1y/ports/` | `StoragePort`, `ExtractorPort` (migration-ready) |
| Adapters | `on1y/adapters/` | SQLite implementation |
| Extract | `on1y/extract/` | Platform plugins + registry |
| Ingestion | `on1y/ingestion/` | RSS poller, enqueue API |
| Pipeline | `on1y/pipeline/` | Processor + worker |

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (optional but recommended for yt-dlp subtitle muxing)

```bash
sudo apt install -y ffmpeg   # WSL / Debian
playwright install chromium  # 知乎 / 小红书 / X
```

## Quick start (WSL)

```bash
cd /home/sijin/On1y
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
cp config/feeds.yaml.example config/feeds.yaml

on1y init
on1y ingest "https://example.com"          # direct extract + store
on1y ingest "https://youtu.be/VIDEO_ID" --queue
on1y worker --once
on1y rss poll
on1y list
on1y show --url "https://example.com"
```

## CLI commands

| Command | Description |
|---------|-------------|
| `on1y init` | Create / migrate SQLite schema |
| `on1y ingest <url>` | Extract and save to `raw_items` |
| `on1y ingest <url> --queue` | Enqueue only |
| `on1y enqueue <url> [--source manual]` | Add to queue |
| `on1y worker [--once]` | Consume `pending_urls` (YouTube: fast metadata only) |
| `on1y subtitles --limit N` | YouTube phase B: fetch subtitles |
| `on1y pipeline youtube` | ingest → subtitles → distill |
| `on1y pipeline zhihu` | Playwright ingest → distill |
| `on1y serve` | FastAPI backend + legacy local web UI ([docs/WEB.md](docs/WEB.md)) |
| `on1y rss poll` | Poll `config/feeds.yaml` for new URLs |
| `on1y rss run --limit N` | Poll + process up to N queued items |
| `on1y rss feeds` / `on1y rss status` | List subscriptions and cursors |

Next.js 14 frontend lives in `frontend/` (tag tree + tri-pane reader), see [docs/WEB.md](docs/WEB.md).

See [docs/RSS.md](docs/RSS.md) for RSSHub setup and cron.
| `on1y list [--platform] [--source]` | List archive |
| `on1y show --url URL` or `--id N` | Show one item |

## Configuration

Environment variables use prefix `ON1Y_` (see `.env.example`).

RSS feeds: copy `config/feeds.yaml.example` → `config/feeds.yaml` (gitignored).

## Data layout

| Path | Purpose |
|------|---------|
| `data/on1y.db` | SQLite (WAL mode) |
| `sql/schema.sql` | Versioned schema (v1) |
| `config/feeds.yaml` | RSS sources (local) |

## Extractors

| Platform | Handler | Method |
|----------|---------|--------|
| YouTube | `YouTubeExtractor` | yt-dlp subtitles only (中英优先，见 `ON1Y_YTDLP_SUB_LANGS`) |
| Bilibili | `BilibiliExtractor` | yt-dlp subtitles only (含 `ai-zh` / `ai-en`) |
| 知乎 | `ZhihuExtractor` | Playwright + cookies |
| 小红书 | `XiaohongshuExtractor` | Playwright + cookies |
| X (Twitter) | `TwitterExtractor` | Playwright + cookies |
| Other | `ArticleExtractor` | Jina Reader → BeautifulSoup fallback |

**登录态（全平台）：** 见 [docs/COOKIES.md](docs/COOKIES.md)。`python scripts/export_cookies.py <platform>` 导出后 `on1y cookies status` 检查，再 `on1y ingest`。

Add a platform: implement `ExtractorPort`, register **before** `ArticleExtractor` in `get_default_registry()`.

## Scheduled RSS (cron)

```cron
*/30 * * * * cd /home/sijin/On1y && ./venv/bin/on1y rss poll >> data/rss.log 2>&1
```

Run worker under `tmux`, `systemd --user`, or a second cron line.

## Development

```bash
pip install -e ".[dev]"
ruff check on1y tests
pytest -q
```

## Roadmap

- **Phase 1**: ingestion + extraction ✅
- **Phase 2**: LLM distillation, tags, relations — **in progress** ([docs/PHASE2.md](docs/PHASE2.md))
- **Phase 2b**: FAISS semantic search
- **Phase 3**: editable knowledge tree, flows, graph UI

```bash
# Phase 2 (requires ON1Y_LLM_API_KEY in .env)
on1y distill --limit 5
on1y distill show --id 8
on1y distill list
```

## License

MIT

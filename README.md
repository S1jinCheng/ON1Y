# On1y

**English** | [简体中文](README.zh-CN.md)

**Turn subscriptions and saves scattered across platforms into a local knowledge base that belongs only to you.**

[License: MIT](LICENSE)
[Release](https://github.com/S1jinCheng/ON1Y/releases/latest)
[Python](https://www.python.org/)
[Platform](https://github.com/S1jinCheng/ON1Y/releases/latest)

[Download](https://github.com/S1jinCheng/ON1Y/releases/latest) · [Quick start](#install--run) · [Demo](#demo) · [Docs](docs/)

---

## Overview

- Data stays on your machine — nothing is uploaded to the cloud
- Multi-user support with backup and migration
- Windows desktop installer — ready to use out of the box

### What it does

| | |
| --- | --- |
| **Ingest** | Bilibili following feed · YouTube channels · Zhihu follows; favorites & Watch Later |
| **Extract** | Video subtitles · Zhihu articles · web article body text |
| **Distill** | LLM summaries, key points, and auto tags (optional) |
| **Search** | Local FTS full-text search over titles, body, and summaries |
| **Organize** | Browse by creator and tags; notes, bookmarks, related items |
| **Extras** | Zhihu hot list · *The Economist* weekly · Kindle delivery |
| **Migrate** | Export `.on1y.zip` and restore on another PC |

---

## Demo

On1y is **local-first**. There is no public online demo — your data and cookies stay on your computer.

*Install → import cookies → sync subscriptions → browse, search, and AI summaries*

---

## Tech stack

| Layer | Technologies |
| --- | --- |
| **Desktop** | [Tauri 2](https://tauri.app/) · WebView2 |
| **Frontend** | [Next.js 14](https://nextjs.org/) · React 18 · TypeScript · Tailwind CSS · Zustand |
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/) · Uvicorn · Pydantic |
| **Storage** | SQLite · FTS5 full-text index |
| **Ingestion** | Bilibili API · RSS / feedparser · yt-dlp |
| **Extraction** | Playwright (Zhihu, etc.) · Jina Reader · BeautifulSoup |
| **AI** | Configurable OpenAI-compatible API (summaries / tags) |
| **Packaging** | PyInstaller · NSIS installer |

```
Feeds / favorites / hot list
    → queue → workers
    → subtitle worker → body extraction
    → SQLite + FTS5
    → FastAPI ←→ Next.js workbench
```

---

## Install & run

### Users: Windows installer (recommended)

1. Download `On1y_*-setup.exe` from [GitHub Releases](https://github.com/S1jinCheng/ON1Y/releases/latest)
2. Run the installer and launch **On1y** from the Start menu
3. Register / sign in → import cookies per [docs/COOKIES.md](docs/COOKIES.md)
4. For YouTube, configure a proxy per [docs/PROXY.md](docs/PROXY.md)
5. In Settings, pick platforms and sync start dates, then run the first sync

Requirements: Windows 10/11 x64 · [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)

### Developers: run from source

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

Frontend (separate terminal):

```powershell
cd frontend
npm install
npm run dev
```

### Common commands

| Command | Description |
| --- | --- |
| `on1y serve` | Start backend and workbench |
| `on1y subscriptions --platform all --ingest` | Sync subscriptions and ingest |
| `on1y cookies status` | Check cookie status |
| `on1y search -q "keyword"` | Full-text search |
| `pytest -q` | Run tests |

---

## Contributing

Issues and pull requests are welcome.

1. **Fork** this repo and create a branch `feat/your-feature`
2. See **Run from source** above and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md); run `ruff check on1y tests` and `pytest -q` before submitting
3. In your PR, briefly explain the motivation and how you tested
4. Do not commit `.env`, `data/`, cookies, or other secrets

## License

[MIT](LICENSE) · [github.com/S1jinCheng/ON1Y](https://github.com/S1jinCheng/ON1Y)

# 全平台登录态（Cookie）配置

On1y **不会**在代码里替你输入账号密码。登录态只能来自**你已登录的浏览器会话**，由你导出一次，程序自动读取。

| 平台 | 技术 | 默认 Cookie 文件 | WSL 推荐导入方式 |
|------|------|------------------|------------------|
| YouTube | yt-dlp + Netscape | `data/cookies/youtube.json` | `import_cookies.py youtube`（须含 **.google.com** 登录 Cookie，见下） |
| Bilibili | yt-dlp + Netscape | `data/cookies/bilibili.json` | `import_cookies.py bilibili` |
| 知乎 | Playwright | `data/cookies/zhihu.json` | `import_cookies.py zhihu` |
| 小红书 | Playwright | `data/cookies/xiaohongshu.json` | `import_cookies.py xiaohongshu` |
| X (Twitter) | Playwright | `data/cookies/twitter.json` | `import_cookies.py twitter` |

`.env` 可覆盖路径，例如 `ON1Y_YOUTUBE_COOKIES_PATH`。

---

## 开源 / Linux 推荐方案：本机安装 Chrome

对开源用户最省事、可复现的路径：

```bash
bash scripts/setup_linux_browser.sh    # 安装 Google Chrome (.deb)
python scripts/export_cookies.py youtube
python scripts/export_cookies.py bilibili
on1y cookies status
```

- Playwright **优先使用系统 Chrome**，不依赖 `playwright install chromium`（Ubuntu 26 上常失败）。
- 需要 **图形界面**：WSL2 + Windows 11 一般自带 **WSLg**；纯 SSH 服务器可用 `import_cookies.py` 或 X11 转发。
- CI / Docker 建议 **Ubuntu 22.04** + `playwright install --with-deps chromium`（见后续 Dockerfile）。

| 方案 | 适合开源 | 说明 |
|------|----------|------|
| Linux + Chrome + `export_cookies.py` | 是 | 默认推荐，文档一条命令 |
| Cookie-Editor + `import_cookies.py` | 是 | 无 GUI 时的备选 |
| Windows 路径 + 中文用户名 | 否 | 贡献者环境差异大，仅作个人备选 |
| 仅 `playwright install chromium` | 部分 | 22.04 可行；26.04 目前不行 |

---

## WSL / Ubuntu 26：`export_cookies.py` 打不开浏览器？

若报错 `Executable doesn't exist` 或 `does not support chromium`，说明 **Playwright 装不了 Chromium**，请用 **方案 A**，不要跑 `playwright install`。

### 方案 A：Cookie-Editor 扩展（推荐）

1. 在 **Windows** Chrome/Edge 登录目标站（youtube.com、bilibili.com 等）
2. 安装扩展 [Cookie-Editor](https://cookie-editor.cgagnier.ca/)
3. 打开该站 → 扩展 → **Export** → 保存为 JSON
4. 在 WSL 导入：

```bash
python scripts/import_cookies.py youtube ~/Downloads/cookies.json
python scripts/import_cookies.py bilibili ~/Downloads/cookies.json
on1y cookies status
```

### 方案 B：在 Windows PowerShell 运行 Playwright 导出

```powershell
cd \\wsl$\<你的发行版>\home\sijin\On1y
python scripts/export_cookies.py youtube
```

生成的 `data/cookies/*.json` 在 WSL 中可直接使用。

### 方案 C：WSL 内已安装 Linux Chrome 时

```bash
python scripts/export_cookies_browser.py youtube --browser chrome
```

---

## 常规流程（Playwright 可用的系统）

```bash
source venv/bin/activate
playwright install chromium

python scripts/export_cookies.py youtube
python scripts/export_cookies.py bilibili
# ...
on1y cookies status
```

## YouTube Cookie 要点

导出时须在 **已登录** 的 `youtube.com` 页面操作（Cookie-Editor → Export）。有效文件通常有 **20+** 条，且包含 `__Secure-1PSID`、`SAPISID` 等 **`.google.com`** 域 Cookie。  
若只有 10 条左右的 `VISITOR_*` / `YSC`，说明是访客态：RSS 订阅列表拉不到，yt-dlp 也会报 “Sign in to confirm you’re not a bot”。

```bash
python scripts/import_cookies.py youtube ~/Downloads/youtube.json
python scripts/sync_youtube_feeds.py   # 或维护 config/youtube_channels.txt
```

---

## 知乎 Playwright：被「安全验证」拦截？

若 ingest 报错含 `安全验证`、`/account/unhuman` 或只抓到标题「进入知乎」，通常是 **自动化指纹** 被知乎识别，而非 Cookie 文件缺失。

On1y 启动 Chrome 时会关闭 `AutomationControlled` 等标志。若仍失败：

1. 重新导出 Cookie：`python scripts/import_cookies.py zhihu <导出.json>`
2. 确认使用系统 Chrome：`bash scripts/setup_linux_browser.sh`
3. 在 Windows 浏览器登录知乎后再导出 Cookie

---

## 代码自动完成的部分

- 读取 `data/cookies/<平台>.json`
- YouTube / B站：转为 `*.json.netscape.txt` 供 yt-dlp
- 知乎 / 小红书 / X：注入 Playwright（抓取时同样需要 Cookie 文件；若 Playwright 不可用则这些平台也需先 `import_cookies.py`）

## 环境变量

```env
ON1Y_REQUIRE_LOGIN_COOKIES=true
ON1Y_YOUTUBE_COOKIES_PATH=./data/cookies/youtube.json
ON1Y_BILIBILI_COOKIES_PATH=./data/cookies/bilibili.json
```

调试可设 `ON1Y_REQUIRE_LOGIN_COOKIES=false`。

## 安全

- `data/cookies/` 已 gitignore，**勿提交仓库**

# On1y Frontend

Next.js App Router frontend for tag-first knowledge browsing.

## Run (WSL)

**先确认用的是 Linux 的 npm，不是 Windows 的 `/mnt/d/npm`：**

```bash
which npm   # 应该是 /usr/bin/npm，不能是 /mnt/d/npm
```

若 `which npm` 显示 `/mnt/d/npm`，在 WSL 里安装：

```bash
sudo apt update
sudo apt install -y nodejs npm
hash -r
```

然后：

```bash
cd frontend
npm install
NEXT_PUBLIC_ON1Y_API_BASE=http://127.0.0.1:8765 npm run dev
```

或从项目根目录：

```bash
chmod +x scripts/dev-frontend.sh
./scripts/dev-frontend.sh
```

## 常见报错

| 现象 | 原因 | 处理 |
|------|------|------|
| `No matching version found for @radix-ui/react-scroll-area@^1.2.11` | npm 上尚无稳定版 1.2.11 | 已改为 `^1.2.10`，重新 `npm install` |
| `UNC 路径不受支持` / `'next' 不是内部或外部命令` | WSL 调用了 Windows 的 npm/cmd | 安装 Linux 版 `nodejs npm`（见上） |

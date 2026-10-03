# iCloud 资料库同步（试用）

设置 → 账号 → 数据 → iCloud 资料库同步。

两端均需使用包含此功能的新版 On1y。第一版通过本地 iCloud Drive 文件夹交换资料，无需同步服务器。两端 On1y 运行时每 30 秒检查一次；退出后 iCloud 仍可传输已经写入的文件，下次打开 On1y 再应用变化。

## 第一次连接

1. 在 Mac 和 Windows 登录同一个 Apple 账户，并启用 iCloud Drive。
2. 第一台电脑选择 iCloud Drive 中的一个新空文件夹，例如 `On1y Library`，勾选创建新资料库和开启文件夹自动同步，然后保存。
3. 在 Finder 中将资料库设为保持下载；Windows 文件资源管理器中选择始终保留在此设备上。
4. 等待 `on1y-library.json` 到达 Windows。Windows 的 On1y 选择对应文件夹并开启同步，**不要再次创建资料库**。
5. 点击同步资料库。分别检查书架、Paper、附件能否打开，再在另一台电脑修改一条笔记验证返回。

必须关闭旧的服务地址同步后才能开启文件夹同步。两个同步方式不能同时使用。已有资料库只允许迁移到包含同一份标识的目录；标识缺失或变更时暂停同步，不能通过新建标识修复。

建议先用独立测试资料库。`scripts/try-icloud-sync.py` 只生成示例 PDF 和 EPUB，并创建两个独立本机数据库验证双向修改，不读取真实账户资料：

```sh
.venv/bin/python scripts/try-icloud-sync.py \
  --folder "$HOME/Library/Mobile Documents/com~apple~CloudDocs/On1y Sync Trial" \
  --local ./build/icloud-trial
```

这验证的是本机 iCloud 目录读写与两个数据库的往返，**不代表已验证 Apple 云端上传或另一台实体 Windows 接收**。设置页的上次本机检查时间同样不是云端送达回执。

## 同步范围

- 订阅/收藏文章、正文、摘要、笔记、批注 HTML、收藏和已读状态、重要程度、标签、自定义主题。
- 书架条目、作者、简介、阅读状态、笔记、标签、主题、封面网址，以及关联电子书。
- Paper 条目、作者、摘要、DOI、年份、期刊、阅读状态、笔记、标签、主题、已有 AI 摘要和关联 PDF。
- 附件支持 PDF、EPUB、MOBI、AZW、AZW3、TXT、DJVU，单文件暂限 2 GiB。

本机数据库、Cookie、账号密码、API Key、Zotero 登录配置、本地绝对路径、抓取队列不进入同步文件夹。论文图像缓存、外部文件夹监控设置、内容关系暂不纳入同步。Zotero 集合名称可同步，本地目录结构和 Zotero 附件关联配置各设备独立保留。

同步后 On1y 使用本机管理的附件副本，原始导入文件保留。通过 On1y 打开副本后保存的编辑会同步；原始导入目录不是通用双向文件镜像。缺少附件或云端文件未下载时，不把它当作删除。更换资料时请从 On1y 内操作。

## 冲突、删除与恢复

不同字段的离线修改自动合并，同一字段的并发修改保留多个版本，可在设置页选择。当前显示版本通过确定性顺序选定，不依赖电脑时钟。PDF/电子书冲突保留完整文件版本，不能自动合并 PDF 内的批注。

删除条目会同步隐藏资料，可在文件夹同步设置的同步回收站中恢复。附件对象和修改历史暂不自动清理，因此占用空间会随文件版本增加。同步不能替代独立备份，也不保证从云端历史中彻底擦除资料。

目录中只有资料库标识、不可变 JSON 修改记录和以内容摘要命名的附件。每台设备的数据库、附件阅读副本、文件校验缓存和已接收事件均在本机。同步记录是明文，附件是原文件；未额外实施 On1y 端到端加密，访问由 iCloud 账户及文件夹权限控制。

第一版适合个人资料库，保留全部事件并扫描目录，暂未实现大规模历史压缩。第一次同步需要复制附件；应预留 iCloud 配额和本机空间。

## 验证

```sh
.venv/bin/python -m pytest -q tests/test_folder_sync.py tests/test_device_sync.py
npm --prefix frontend test -- --run src/components/folder-sync-settings.test.tsx src/components/device-sync-settings.test.tsx
```

覆盖独立数据库、附件校验、双向编辑、断网重试、乱序到达、冲突选择、回收站恢复、账号隔离、凭据排除和前端开启流程。

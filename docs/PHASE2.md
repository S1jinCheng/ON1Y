# Phase 2 & 3 架构说明

Phase 1 已完成：**订阅 → 入队 → 提取 → `raw_items`**。  
Phase 2 在原文之上做 **LLM 蒸馏（摘要、标签、主题）**；Phase 3 做 **条目之间的显式关系与可编辑知识树**。

## 总流水线

```text
Phase 1  raw_items          （原文 / 字幕 / 简介）
    ↓ on1y distill
Phase 2  distilled_items     （摘要、要点）
           tags + item_tags  （分类标签，可树形）
           item_relations    （条目间关系，Phase 2 可由 LLM 建议，Phase 3 可人工改）
    ↓ （后续）embed + FAISS
Phase 2b 向量检索、相似推荐
    ↓ Phase 3
Phase 3  knowledge_nodes     （用户可编辑的主题树 / 子集）
           规则流、合并视图
```

## Phase 2：LLM 分类与蒸馏

### 输入 / 输出

| 输入 | 输出表 |
|------|--------|
| `raw_items`（`extract_status` 为 ok/partial，有正文） | `distilled_items` |
| 同上 | `tags` + `item_tags`（自动建标签） |
| 同上 | `item_relations`（仅当 LLM 能指向库内已有 URL） |

### LLM 配置

**推荐：Web 控制台填写**（`on1y serve` → 页面顶部「LLM 设置」）  
保存到 `data/llm_settings.json`，无需写进 `.env`。

### 锯齿云 / 其他 OpenAI 兼容中转

若 API Key 来自 **锯齿云** 等第三方（不是 DeepSeek 官网申请），必须：

1. **Base URL** 填平台文档里的网关地址（常见 `https://你的域名/v1`），**不要**用 `https://api.deepseek.com`
2. **模型名** 填平台「模型列表」里的 ID（可能与 `deepseek-v4-flash` 不完全一致）
3. 保存后点 **「测试连接」**，成功再跑蒸馏

官方直连默认使用 **DeepSeek-V4-Flash**：

| 项 | 值 |
|----|-----|
| Base URL | `https://api.deepseek.com` |
| Model | `deepseek-v4-flash` |

也可用 `.env`（优先级低于 Web 保存的文件）：

```env
ON1Y_LLM_BASE_URL=https://api.deepseek.com
ON1Y_LLM_API_KEY=sk-...
ON1Y_LLM_MODEL=deepseek-v4-flash
```

### 命令

```bash
# 处理尚未蒸馏的条目（默认最多 10 条）
on1y distill --limit 10

# 指定一条
on1y distill --id 8

# 重新蒸馏
on1y distill --id 8 --force

# 查看结果
on1y distill list
on1y distill show --id 8
```

### 标签树（子集的雏形）

`tags.parent_id` 形成树，例如：

```text
科技
 ├── AI
 └── 创业
生活
 └── 旅行
```

LLM 返回 `tags: [{ "name": "AI", "parent": "科技" }]` 时自动创建父子标签。  
**Phase 3** 会把这棵树升级为用户可拖拽编辑的 `knowledge_nodes`，并支持「某条内容属于多个分支」。

## Phase 3：信息串联与子集（规划）

| 能力 | 数据 | 说明 |
|------|------|------|
| 显式关系 | `item_relations` | `same_topic` / `references` / `subset_of` / `series` / `contradicts` |
| 子集 | `relation_type=subset_of` 或 tag 父子 | 「这篇文章是『AI 安全』主题下的一个子话题」 |
| 系列 | `series` + `source_meta` | 同一 UP 主、同一播客系列 |
| 用户覆盖 | `knowledge_nodes` + `node_items` | 可编辑主题，拖拽归档 |
| 检索串联 | FAISS + 关系图 | 「和这条相似 / 同主题 / 被引用」 |

关系来源优先级（建议）：

1. 用户手动（Phase 3）
2. LLM 建议（Phase 2，`item_relations`）
3. 规则：同 `feed_label`、同平台频道、标题相似度
4. 向量近邻（FAISS）

## 与现有 Web UI

- Phase 1：`on1y serve` — 订阅 / 队列 / 入库
- Phase 2（后续）：增加「蒸馏 / 标签 / 关系」标签页
- Phase 3：知识树编辑器

## 实现顺序建议

1. ✅ Schema v2 + `on1y distill`（本阶段）
2. 批处理队列 `pending_distill` 或 cron `on1y distill --limit 20`
3. FAISS 分块嵌入 + `on1y search "query"`
4. Web UI 展示标签与关系图
5. `knowledge_nodes` 用户编辑

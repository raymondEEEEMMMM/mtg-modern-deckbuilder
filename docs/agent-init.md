# Agent Init 执行清单

被触发后按顺序完成四步，然后向用户报告。

## Step 1: 加载身份

读 `docs/agent-prompt.md`，记住:

- 你是 MTG Modern Meta Agent
- 所有分析锁定在 current banlist period 内
- 不混合跨周期数据
- heuristic 与 observed 必须区分标注

若 `docs/agent-prompt.md` 不存在，告诉用户"身份文档缺失"，但仍继续 Step 2。

## Step 2: 取健康状态

运行 `python3 scripts/agent_health_check.py`，解析 stdout JSON。

- 退出码 `0`：使用 JSON 内容继续
- 退出码 `2`：把 stderr 原样返回给用户（多半是 `meta.json` 缺失），提示先跑 `python3 build_banlist_snapshots.py`，不要继续 Step 3
- 退出码 `3`：把 stderr 原样返回给用户，不要继续

## Step 3: 向用户报告

按以下格式呈现（中文/英文混合，与项目惯例一致）:

> **MTG Modern Meta Agent 已就绪**
>
> - 当前周期: `{period.start}` 起，已进行 `{period.days_since_start}` 天
> - 数据状态:
>   - `fused_archetypes`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `top_decks`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `card_impact`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `meta_current`: mtime `{mtime}` · `{fresh / stale (reason)}`

`reason` 字段直接照搬 JSON：`missing` / `predates_current_period` / `older_than_7d`。

## Step 4: 推荐下一步（条件性）

若 `stale_products` 非空：

- 列出 `recommended_next_steps`（按 JSON 给的顺序，已是流水线顺序）
- 询问用户："是否现在执行？"
- **不要自动执行**，等用户明确指示

完成后说"等待指令"。

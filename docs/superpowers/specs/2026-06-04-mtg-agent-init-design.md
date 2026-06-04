# MTG Agent Init — 跨平台初始化 Skill 设计

- **Date:** 2026-06-04
- **Status:** Draft — pending user review
- **Scope:** 一个新的 `agent-init` skill，跨 Claude Code / CodeBuddy / OpenClaw 三平台，负责在会话开始时加载 MTG Modern Meta Agent 的身份与上下文。

---

## 1. 背景与动机

当前项目里 agent 的"身份"分散在两处：

- `docs/agent-prompt.md` —— 角色、原则、流水线顺序、policy（静态）
- `mtg_modern_data/ban_list/meta.json` —— 当前 B&R 周期起止（动态）

加上 4 个产物（`fused_archetypes` / `top_decks` / `card_impact` / `meta/current.json`）的新鲜度，agent 在开新会话时要"自己想起来去查这些"，容易遗漏。已有 4 个领域 skill（top8/goldfish/card-impact/banlist）解决的是"做某件事"，不解决"开局是什么状态"。

CLAUDE.md 这类方案只对 Claude Code 一家有效；CodeBuddy 用 `.codebuddy/rules/*.mdc`，OpenClaw 没有直接等价物。**Skill 是三个平台唯一的公共子集**，因此跨平台 init 必须做成 skill。

## 2. 目标

一个被触发的 `agent-init` skill，做四件事：

1. **加载身份** —— 读 `docs/agent-prompt.md`，进入"MTG Modern Meta Agent"角色，记住其原则与 policy。
2. **报告当前周期** —— 推出 `current_period.start`，告知用户"当前周期从 YYYY-MM-DD 开始，已进行 N 天"。
3. **报告数据新鲜度** —— 列出 4 个关键产物的 mtime，标注是否过期及过期原因。
4. **必要时推荐下一步** —— 若有产物过期，给出对应的"建议先跑哪个命令再开始分析"，并询问用户是否现在跑。

完成后 agent 说一句"已就绪，等待指令"。**不重复列 4 个领域 skill**——它们由各平台 skill 加载机制自行管理。

## 3. Non-Goals（明确不做）

- 不自动运行任何爬虫或评估脚本（推荐由用户决定是否执行）
- 不修改 `docs/agent-prompt.md` 的现有内容
- 不引入跨平台 skill sync 脚本（当前只有 1 个跨平台 skill，手维护成本更低）
- 不替代或废弃 4 个现有领域 skill
- 不做 SessionStart hook 注入（用户没要求自动触发，且 hook 是 Claude Code 专属）

## 4. 架构概览

```
docs/agent-init.md                        # 唯一正文（init 执行清单）
scripts/agent_health_check.py             # 确定性健康检查，输出 JSON

.claude/skills/agent-init/SKILL.md        # Claude Code 薄壳
.codebuddy/skills/agent-init/SKILL.md     # CodeBuddy 薄壳
skills/agent-init/SKILL.md                # OpenClaw 薄壳（新建根目录）

tests/test_agent_health_check.py          # 脚本单元测试
```

模块边界：

| 模块 | 职责 | 依赖 |
|------|------|------|
| `agent_health_check.py` | 确定性检查 + 输出结构化 JSON | `scripts/period_utils.py`、文件系统 |
| `docs/agent-init.md` | 描述 agent 看到 JSON 后该如何呈现 | `docs/agent-prompt.md`、健康检查脚本 |
| 三份 SKILL.md | 平台 frontmatter + 一句"按清单执行" | `docs/agent-init.md` |

## 5. `scripts/agent_health_check.py`

### 输入
无 CLI 参数。可选 `--json`（默认）或 `--text`（人类可读，用于调试）。

### 数据来源
- `mtg_modern_data/ban_list/meta.json` → 复用 `scripts/period_utils.load_period_start_from_meta()` 取最新 `changes_history[].effective_date`
- 这 4 个产物文件的 `Path.stat().st_mtime`：
  - `mtg_modern_data/decks/processed/fused_archetypes.json`
  - `mtg_modern_data/decks/top_n/top_decks.json`
  - `mtg_modern_data/cards/card_impact.json`
  - `mtg_modern_data/meta/current.json`

### 过期判定（按优先级）
1. 文件**不存在** → `stale: true, reason: "missing"`
2. mtime **早于 current_period.start** → `stale: true, reason: "predates_current_period"`
3. mtime **超过 7 天未更新** → `stale: true, reason: "older_than_7d"`
4. 否则 → `stale: false`

### `recommended_next_steps` 映射表
每个 stale 产物对应一组生成命令（按需多条）：

| 过期产物 | 推荐命令（按顺序） |
|----------|------------------|
| `fused_archetypes` | `python3 scrape_decklists_top8.py --max-events 999`<br>`python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap` |
| `top_decks` | `python3 evaluate_deck_strength.py --top 15` |
| `card_impact` | `python3 scripts/build_card_impact.py` |
| `meta/current.json` | `python3 compose_meta.py` |

输出规则：
1. 对每个 stale 产物，按主流水线顺序（fused_archetypes → top_decks → card_impact → meta）插入对应命令
2. 同一条命令在最终列表中**只出现一次**（即使多个 stale 产物都映射到它，例如 fused_archetypes 的两条 scrape 命令）
3. 不做依赖推断（用户自己决定要不要顺带重跑下游）

### 输出 JSON 结构
```json
{
  "generated_at": "2026-06-04T12:34:56",
  "period": {
    "start": "2026-05-18",
    "today": "2026-06-04",
    "days_since_start": 17
  },
  "products": [
    {
      "name": "fused_archetypes",
      "path": "mtg_modern_data/decks/processed/fused_archetypes.json",
      "exists": true,
      "mtime": "2026-06-03T10:30:00",
      "days_old": 1,
      "stale": false,
      "reason": null
    },
    {
      "name": "card_impact",
      "path": "mtg_modern_data/cards/card_impact.json",
      "exists": true,
      "mtime": "2026-05-10T08:00:00",
      "days_old": 25,
      "stale": true,
      "reason": "predates_current_period"
    }
  ],
  "stale_products": ["card_impact"],
  "recommended_next_steps": [
    "python3 scripts/build_card_impact.py"
  ]
}
```

### 退出码
- `0` —— 脚本本身执行成功（无论数据是否 stale）
- `2` —— meta.json 不可读或 period 解析失败
- `3` —— 其他不可恢复异常

### 测试覆盖（pytest）
- 全部产物新鲜 → 空 `stale_products`、空 `recommended_next_steps`
- 一个产物 mtime 早于 period.start → reason = "predates_current_period"
- 一个产物文件不存在 → reason = "missing"
- 一个产物 mtime 在 period 内但 > 7 天 → reason = "older_than_7d"
- 多个产物 stale → recommended 按主流水线顺序排列，同一条命令不重复
- `meta.json` 不存在 → 退出码 2

## 6. `docs/agent-init.md`

正文(给 agent 看的执行清单)：

```markdown
# Agent Init 执行清单

被触发后按顺序完成四步，然后向用户报告。

## Step 1: 加载身份
读 `docs/agent-prompt.md`，记住:
- 你是 MTG Modern Meta Agent
- 所有分析锁定在 current banlist period 内
- 不混合跨周期数据
- heuristic 与 observed 必须区分标注

## Step 2: 取健康状态
运行 `python3 scripts/agent_health_check.py`,解析 stdout JSON。
若退出码非 0,直接告诉用户脚本失败并附上错误,不要继续推断。

## Step 3: 向用户报告
按以下格式呈现:

> **MTG Modern Meta Agent 已就绪**
>
> - 当前周期: `period.start` 起,已进行 `period.days_since_start` 天
> - 数据状态:
>   - `fused_archetypes`: <mtime> · <fresh / stale (reason)>
>   - `top_decks`: ...
>   - `card_impact`: ...
>   - `meta/current.json`: ...

## Step 4: 推荐下一步(条件性)
若 `stale_products` 非空:
- 列出 `recommended_next_steps`
- 询问用户:"是否现在执行?"
- **不要自动执行**,等用户明确指示

完成后说"等待指令"。
```

设计要点：
- 全部业务格式都集中在这一份文件
- 三份 SKILL.md 不重复这些细节，只指向这里
- 修改报告格式只改一处

## 7. SKILL.md 薄壳

三家共用的正文（5 行）:
```markdown
# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

### 7.1 Claude Code 版本（`.claude/skills/agent-init/SKILL.md`）

```markdown
---
name: agent-init
description: Use at the start of a session or whenever the user wants to enter MTG Modern Meta Agent mode. Triggers include "initialize MTG agent", "start MTG session", "进入 MTG 模式", "加载 agent 身份", "begin meta analysis". Loads agent persona, reports current banlist period, and checks freshness of key data products.
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

### 7.2 CodeBuddy 版本（`.codebuddy/skills/agent-init/SKILL.md`）

```markdown
---
name: agent-init
description: MTG Modern Meta Agent initialization skill. This skill should be used at session start, or whenever the user wants the agent to assume the MTG Modern Meta Agent role and verify the local knowledge base state. Loads agent persona from docs/agent-prompt.md, detects the current banlist period from ban_list/meta.json, runs a deterministic health check on the four key data products (fused_archetypes, top_decks, card_impact, meta/current.json), and recommends next steps if any product is stale. Triggers on: starting a new MTG analysis session, "initialize agent", "进入 MTG 模式", "load context", or whenever the agent needs to confirm its operating state and data freshness before answering questions.
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

### 7.3 OpenClaw 版本（`skills/agent-init/SKILL.md`）

```markdown
---
name: agent-init
description: Use at the start of a session or whenever the user wants to enter MTG Modern Meta Agent mode. Triggers include "initialize MTG agent", "start MTG session", "进入 MTG 模式", "加载 agent 身份". Loads agent persona, reports current banlist period, checks data freshness.
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    os: ["darwin", "linux"]
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

为 OpenClaw 新建 `skills/` 根目录(此前不存在),并向 `.gitignore` 确认不会忽略它。

## 8. 数据流

```
用户说"初始化 agent"
        ↓
平台匹配 description 触发 agent-init
        ↓
agent 加载 SKILL.md 正文
        ↓
agent 读 docs/agent-init.md(完整清单)
        ↓
Step 1: 读 docs/agent-prompt.md(身份)
Step 2: 跑 scripts/agent_health_check.py → JSON
Step 3: 按格式向用户报告周期 + 数据新鲜度
Step 4: 若 stale,列出推荐命令并询问
        ↓
agent 说"已就绪,等待指令"
```

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| `docs/agent-prompt.md` 不存在 | agent 报告"身份文档缺失",仍尝试 Step 2 |
| `scripts/agent_health_check.py` 退出码非 0 | agent 把脚本 stderr 原样返回给用户,不进行下一步 |
| `meta.json` 不存在 | 脚本退出 2,agent 提示"先跑 build_banlist_snapshots.py" |
| 某个产物文件读取异常 | 脚本将该产物标 `exists: false`,继续处理其他产物 |

不在这里包装 fallback、不发明默认周期——任何缺失都明确报告。

## 10. 测试

- `tests/test_agent_health_check.py`(pytest)覆盖 §5 列出的 6 个用例
- skill 本身的端到端测试由 manual smoke 完成(在三个平台各触发一次,核对输出格式与 §6 描述一致),无需自动化

## 11. 实现顺序

1. 写 `scripts/agent_health_check.py` + 单测,跑通 pytest
2. 写 `docs/agent-init.md`
3. 在 Claude Code 平台手动触发一次薄壳,核对输出
4. 复制薄壳到 CodeBuddy 和 OpenClaw 目录,调整 frontmatter
5. 更新 `README.md` 的"可用 Skills"小节,增加 agent-init
6. commit

## 12. 风险与开放问题

- **风险:**`mtime` 在 git checkout 后会被刷新,可能让 stale 判定不准。**缓解:** 在 §5 reason 里加 `"mtime_likely_unreliable_after_checkout"`(可选,后续若发现误报再加)。
- **开放问题:** 7 天 stale 阈值是否合理?目前 Modern Meta 平均 30-90 天换一次周期,7 天足够保守;若用户反馈过严再调。
- **开放问题:** OpenClaw 在该项目实际是否有用户在用?若无,§7.3 暂时是"预留",不会被任何人触发。

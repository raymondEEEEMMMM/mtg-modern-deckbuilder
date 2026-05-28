---
name: mtg-modern-workflow
description: MTG Modern deck expert agent workflow - period-based meta analysis and deck building
metadata:
  type: project
---

## 目标
构建一个万智牌摩登赛制（Modern）组牌专家Agent

## 核心工作流程

### 阶段1：周期划定
- **禁牌表周期**：两次相邻banlist变更之间的时间段定义为一个"Meta周期"
- **周期命名**：以banlist变更生效日期命名，如 `2026-05-18` 周期
- **数据更新时间**：以禁牌表变动日期作为数据采集和分析的分割点
- 识别当前所处的Meta周期，以此为起点划定评估范围
- **已实现**：`build_banlist_snapshots.py` 从TIMELINE生成28个历史快照（2011-08~2026-05），`meta.json` 记录全部周期信息与当前周期

### 阶段2：套牌数据收集与分析
- **数据来源与采集方式**：
  - **MTGTop8**：爬虫抓取赛事Decklists和archetype统计 ✅ 已实现 (`scrape_decks_mtgtop8.py`)
  - **MTGGoldfish**：浏览器抓取Metagame页面 ✅ 已实现 (`scrape_decks_goldfish.py`，含key_cards/名次/分平台)
  - **Scryfall API**：按需查询卡牌规则、费用、合法性格式（不维护全量本地库）
  - **MTGO/Magic Arena**：线上赛结果（通过第三方聚合获取）
- **赛事级别权重系统**（详见 `decks/tier_config.json`、`decks/fusion_config.json`）：

  | 级别 | 权重 | 置信度 | 典型赛事 |
  |------|------|--------|----------|
  | Professional | 1.0 | high | Pro Tour, Regional Championship |
  | Major | 0.8 | high | SCG CON, RCQ 1K, MagicFest |
  | Competitive | 0.6 | medium | MTGO Challenge 32/64, RCQ |
  | Regular | 0.3 | low | MTGO League, 本地小店赛 |

  - MTGO League仅提交5-0战绩，存在严重选择偏差，低权重抑制虚高
  - 有效样本量 = Σ(每副套牌的tier_weight)，而非简单计数

- **多源融合权重**（详见 `decks/fusion_config.json`）：

  | 数据源 | 融合权重 | 置信度 | 核心优势 | 核心缺陷 |
  |--------|----------|--------|----------|----------|
  | MTGTop8 | 0.6 | medium_high | 全量archetype(40+), 预分类 | 无名次数据, 聚合不透明 |
  | MTGGoldfish | 0.4 | medium | 名次数据, key_cards验证 | 只Top15, League膨胀 |

  - **League膨胀修正**：Goldfish的metagame_share中League占~60%样本但严重选择偏差
  - 修正公式：`corrected_share = raw_share × (1 - 0.35)`
  - 验证：Affinity修正后10.7% ≈ Top8的12%，修正合理

- **周期关联**：根据 `meta.json` 中 `current_period` 的 `start_date` 划定数据采集时间范围，只采集当前周期内的比赛数据
- **数据维度**：
  - 套牌胜率 (win_rate)
  - 出场率/环境占比 (metagame_share)
  - 不同赛事表现（地区赛、线上赛、大型公开赛）
  - 对阵表现（与主要对手的胜负情况）
  - 套牌卡牌组成比例（威胁、干扰、地牌比例等）
- **多源数据对比**：

  | 维度 | MTGTop8 | MTGGoldfish |
  |------|---------|-------------|
  | 出场率 | ✅ | ✅ |
  | archetype分类 | ✅ 预分类 | ❌ 需自行分类 |
  | 套牌数量 | ✅ 完整列表 | ✅ (Top 15) |
  | 核心卡牌 (key_cards) | ❌ | ✅ 每archetype 3张 |
  | 名次数据 (placement) | ❌ | ✅ 1st~8th, 5-0 |
  | Paper/MTGO分平台 | ❌ | ✅ |
  | 赛事级别 | ✅ | ✅ |

  - 命名差异示例：Goldfish "Belcher" = Top8 "Landless"，Goldfish "Boros Energy" ≈ Top8 "Boros Aggro"
  - 多源融合时需建立archetype名称映射表
- **采集频率**：每个新ban周期开始时触发全量采集，周期内每周增量更新

### 阶段3：套牌强度评估 ✅ 已实现
- **模型设计** (`evaluate_deck_strength.py`)：
  - 基于真实decklist数据（153套MTGTop8全量75卡decklist）
  - 强度评分公式：`strength = 0.35×meta_share + 0.30×perf_score + 0.15×consistency + 0.10×power_density + 0.10×tournament_win`
  - meta_share：真实出场率（decklist计数 + Goldfish/Top8聚合加权融合，全局归一化后 Σ=1.0）
  - perf_score：名次表现，从Goldfish赛事名次数据计算
  - consistency：构筑一致性，同一archetype内卡牌重合度
  - power_density：高使用率卡牌集中度
  - tournament_win：冠军/决赛指标
- **Tier分级**：
  - Tier 1：score ≥ 50
  - Tier 2：score ≥ 25
  - Tier 3：score ≥ 10
  - Tier 4：其余（小众/冷门）
- **Archetype映射**：基于卡牌相似度自动归并 + 手动规范名映射
- **输出**：
  - `decks/processed/fused_archetypes.json` — 全量融合数据（含真实key_cards、consistency、power_density）
  - `decks/top_n/top_decks.json` — Top N排名
- 对抗性分析，评估套牌面对Meta中其他主流套牌的表现
- 结合禁牌表变动，预测某些卡牌被禁或解禁对套牌强度的影响
- 每个套牌的核心卡牌列表及其功能介绍

### 阶段4：组合环境Meta ✅ 已实现
- **模型设计** (`compose_meta.py`)：
  - 利用Phase 3的fused_archetypes数据，构建当前环境Meta结构
  - 统计Meta中各类套牌类型比例（快攻37.8%、控制19.8%、中速10.0%、Combo32.4%）
  - 计算Meta覆盖率（Top 10覆盖42.8%，Top 15覆盖53.5%）
  - 构建Top N对阵矩阵（基于category heuristics + strength_score差值）
  - 识别Meta角色：dominant / established / niche / meta_call
  - 禁牌影响评估：追踪当前周期禁牌变动对archetype的冲击
- **输出**：`meta/current.json` — 完整Meta快照

### 阶段5：组牌结构建议

#### 用户输入需求（必需）

用户需提供以下指标，系统据此结合Phase 3/4数据生成组牌建议：

| 指标 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| **archetype** | string | ✅ | 目标archetype名称，需匹配`fused_archetypes.json`中的canonical name | `"Boros Energy"`, `"Affinity"`, `"Living End"` |
| **gameplan** | enum | ✅ | 战略意图，决定主牌/备牌的侧重方向 | 见下方gameplan枚举 |
| **power_level** | enum | ✅ | 目标竞技强度，影响卡牌选择上限和备牌针对深度 | 见下方power_level枚举 |

**gameplan 枚举值：**

| 值 | 含义 | 对组牌的影响 |
|----|------|-------------|
| `aggro_overwhelm` | 快速倾泻威胁，在对手站住前取胜 | 主牌最大化威胁密度，减少3费+卡牌，备牌保留少量反制 |
| `tempo_disrupt` | 早期威胁+点射干扰，节奏压制 | 主牌平衡威胁/干扰比≈6:4，备牌增加针对性干扰 |
| `grind_value` | 中后期资源碾压，一换多取胜 | 主牌增加卡牌优势和过滤器，备牌强化持久战能力 |
| `control_stabilize` | 清场+制控，拖到后期用少量制胜件获胜 | 主牌大量交互（去解、反击），制胜件仅2-4张，备牌更精细的针对性 |
| `combo_assemble` | 尽快集齐组合件一轮击杀 | 主牌最大化组合件浓度+滤抽，备牌放保护件和备用plan |
| `synergy_engine` | 依赖卡牌间协同效应滚雪球 | 主牌围绕引擎核心展开，备牌保留引擎被拆后的备选线路 |

**power_level 枚举值：**

| 值 | 含义 | 对组牌的影响 |
|----|------|-------------|
| `competitive` | Tier 1-2竞技强度，追求最优解 | 不考虑预算，使用最优legal卡牌，备牌针对全部主流archetype |
| `semi_competitive` | Tier 2-3强度，有一定竞争力 | 允许个别非最优替代，备牌针对Tier 1-2主流 |
| `budget` | 经济型构筑 | 替代高价卡牌（≥$20），接受强度折损，备牌聚焦最常见对手 |
| `casual` | 休闲/教学用 | 以卡牌可获取性和操作简易度为优先，弱化针对性 |

#### 用户输入需求（可选）

| 指标 | 类型 | 说明 | 示例 |
|------|------|------|------|
| **target_matchups** | string[] | 希望重点针对的archetype列表 | `["Boros Energy", "Affinity"]` |
| **avoid_cards** | string[] | 不希望使用的卡牌（个人偏好/已拥有反代） | `["Ragavan, Nimble Pilferer"]` |
| **preferred_colors** | string[] | 偏好颜色（若archetype有多色变体时参考） | `["U", "R"]` |


#### 输出结构

根据用户输入 + Phase 3/4 Meta数据，生成以下维度的组牌建议：

1. **地牌配置**：地牌数量、类型分布（基础地/双色地/特殊地）、颜色产出来源比例
2. **主牌结构**：
   - 威胁（Win Conditions）：数量/比例，核心制胜件
   - 交互（Interaction）：去除/反击/手牌破坏的数量/比例
   - 滤抽/引擎（Filter/Engine）：过牌和协同引擎件
3. **备牌策略**：针对具体主流archetype的替换方案（入备/出备对照表）
4. **弱点分析**：该archetype的固有弱点 + 当前Meta中的不利对局
5. **Meta定位**：该archetype在当前Meta中的角色（dominant/established/niche/meta_call）及对阵矩阵概览

#### 输入输出Schema

**输入** (`user/deck_requests.json`)：
```json
{
  "request_id": "uuid",
  "created_at": "YYYY-MM-DDTHH:mm:ssZ",
  "archetype": "Boros Energy",
  "gameplan": "aggro_overwhelm",
  "power_level": "competitive",
  "target_matchups": ["Affinity", "Grixis Reanimator"],
  "avoid_cards": [],
  "preferred_colors": [],
  "avoid_cards": []
}
```

**输出** (`user/deck_suggestions/{request_id}.json`)：
```json
{
  "request_id": "uuid",
  "generated_at": "YYYY-MM-DDTHH:mm:ssZ",
  "based_on_meta_date": "YYYY-MM-DD",
  "archetype": "Boros Energy",
  "category": "aggro",
  "gameplan": "aggro_overwhelm",
  "power_level": "competitive",
  "meta_context": {
    "tier": "Tier 1",
    "strength_score": 83.3,
    "metagame_share": 0.0671,
    "meta_role": "dominant"
  },
  "deck_structure": {
    "lands": { "count": 20, "distribution": { "basic": 6, "dual": 10, "utility": 4 } },
    "threats": { "count": 24, "ratio": 0.387, "core": ["Ragavan, Nimble Pilferer", "Ocelot Pride"] },
    "interaction": { "count": 10, "ratio": 0.161, "core": ["Galvanic Discharge", "Lightning Bolt"] },
    "filter_engine": { "count": 8, "ratio": 0.129, "core": ["Ajani, Nacatl Pariah", "Guide of Souls"] }
  },
  "sideboard_strategy": [
    {
      "target_archetype": "Affinity",
      "side_in": ["Stony Silence", "Shattering Spree"],
      "side_out": ["Ocelot Pride", "Guide of Souls"],
      "rationale": "Affinity依赖神器地+Mox Opal，Stony Silence封锁其法术力基础"
    }
  ],
  "weaknesses": [
    { "type": "sweepers", "description": "面对Supreme Verdict/Wrath of God等全场去除脆弱", "mitigation": "备牌Guide of Souls提供不灭保护" }
  ],
  "matchup_overview": {
    "favorable": ["Living End", "Amulet Titan"],
    "unfavorable": ["Dimir Midrange", "Sultai Midrange"],
    "even": ["UR Prowess", "Red Deck Wins"]
  }
}
```

### 阶段6：多工具和技能支持
- **数据分析工具**：用于数据处理和模型训练
- **自然语言处理技能**：理解用户需求，解释套牌和策略
- **知识库与规则引擎**：内置最新禁牌表、卡牌规则和策略知识
- **用户交互模块**：通过对话或界面收集用户偏好和目标

### 内置技能（Skills）

| Skill | 文件位置 | 功能 |
|-------|---------|------|
| `mtg_banlist` | `.claude/skills/mtg_banlist/` | 查询Modern禁牌表，支持按名称搜索、历史存档查询 |
| `mtg_scrape_top8_decklists` | `.codebuddy/rules/mtg_scrape_top8_decklists.mdc` | 从MTGTop8爬取全量75卡decklist + 禁牌合法性校验 |

**mtg_banlist 使用方式：**
```bash
python3 .claude/skills/mtg_banlist/banlist_tool.py [选项] [搜索词]

# 选项：
#   无参数          - 显示当前全部禁牌
#   Ponder          - 搜索特定卡名
#   --history       - 显示可用的历史快照列表
#   --date 2024-08-26  - 查看指定日期的禁牌快照
#   --diff 2024-08-26  - 对比历史与当前的差异
```

**mtg_scrape_top8_decklists 使用方式：**
```bash
python3 scrape_decklists_top8.py [--max-events N] [--skip-existing]

# 选项：
#   --max-events 25   - 最多爬取25个赛事（默认999）
#   --skip-existing   - 跳过已爬取的赛事（增量模式，暂未实现）

# 输出：mtg_modern_data/decks/raw/decklists/YYYY-MM-DD_top8_decklists.json
# 依赖：pip install playwright && playwright install chromium
```

### 构建工具

| 工具 | 文件 | 功能 |
|------|------|------|
| `build_banlist_snapshots.py` | 项目根目录 | 从TIMELINE常量生成全部历史快照文件和current.json |
| `scrape_timeline.py` | 项目根目录 | 辅助脚本：从网络抓取B&R时间线数据 |
| `scrape_decks_mtgtop8.py` | 项目根目录 | 从MTGTop8采集Modern环境数据（archetype分布+赛事列表） |
| `scrape_decks_goldfish.py` | 项目根目录 | 从MTGGoldfish采集Modern环境数据（含key_cards/名次/分平台） |
| `evaluate_deck_strength.py` | 项目根目录 | 阶段3：基于真实decklist数据融合多源，计算强度评分和Tier分级 |
| `compose_meta.py` | 项目根目录 | 阶段4：构建Meta结构（composition/matchup/banlist impact） |
| `scrape_decklists_top8.py` | 项目根目录 | 从MTGTop8爬取全量75卡decklist，含禁牌合法性校验 |
| `generate_report.py` | 项目根目录 | 生成HTML环境报告 |

## 技术栈
- Agent: mtg-modern-deckbuilder (专用)
- Tools: WebSearch, WebFetch, Bash
- 数据源: Scryfall, MtgGoldfish, MTGTop8, MTG官方赛事数据, Magic Arena, MTGO

## 数据存储结构

```
mtg_modern_data/                    # ✅ 已创建目录结构
├── ban_list/                       # 禁牌表存档
│   ├── current.json                # 当前生效的禁牌表 ✅ 已创建
│   ├── meta.json                   # 禁牌表元数据 ✅ 已创建
│   └── history/                    # 历史禁牌表
│       └── YYYY-MM-DD.json         # 每次禁牌变动的存档
├── decks/                          # 套牌数据
│   ├── raw/                        # 原始采集数据
│   │   ├── YYYY-MM-DD_mtgtop8.json  # MTGTop8数据 ✅ 已创建
│   │   └── YYYY-MM-DD_goldfish.json # Goldfish数据（含key_cards/名次/League修正） ✅ 已创建
│   ├── decklists/                  # 全量decklist数据
│   │   └── YYYY-MM-DD_top8_decklists.json # 全量75卡decklist+合法性校验 ✅ 已创建
│   ├── tier_config.json            # 赛事级别权重配置 ✅ 已创建
│   ├── fusion_config.json          # 多源融合权重与置信度配置 ✅ 已创建
│   ├── processed/                  # 清洗处理后数据
│   │   └── fused_archetypes.json   # 多源融合archetype数据 ✅ 已创建
│   └── top_n/                      # Top N套牌输出
│       └── top_decks.json          # 排名输出 ✅ 已创建
├── meta/                           # Meta分析结果
│   ├── current.json                # 当前环境Meta ✅ 已创建
│   └── history/                    # 历史Meta快照
├── cards/                          # 卡牌数据（Scryfall API缓存） ✅ 已创建模板
│   └── cache/                      # 按需缓存的卡牌数据
│       └── {card_name_slug}.json
└── user/                           # 用户数据 ✅ 已创建模板
    ├── preferences.json
    ├── deck_requests.json          # Phase 5 用户组牌请求（输入）
    └── deck_suggestions/           # Phase 5 组牌建议输出
        └── {request_id}.json      # 每次请求对应的完整建议
```

### 数据Schema定义

#### 1. ban_list/current.json - 当前禁牌表
```json
{
  "format": "Modern",
  "effective_date": "YYYY-MM-DD",
  "last_updated": "YYYY-MM-DDTHH:mm:ssZ",
  "banned": ["card_name_1", "card_name_2"],
  "restricted": [],
  "deck_banned": []
}
```

#### 2. ban_list/history/YYYY-MM-DD.json - 历史禁牌表
```json
{
  "format": "Modern",
  "effective_date": "YYYY-MM-DD",
  "previous_date": "YYYY-MM-DD",
  "changes": {
    "added_banned": ["newly_banned_card"],
    "removed_banned": ["unbanned_card"],
    "added_restricted": [],
    "removed_restricted": []
  },
  "banned": ["..."],
  "source_url": "https://...",
  "notes": "变更说明"
}
```

#### 3. decks/raw/YYYY-MM-DD.json - 原始套牌数据
```json
{
  "collected_date": "YYYY-MM-DD",
  "source": "MTGGoldfish|MTGTop8|Scryfall|...",
  "source_url": "https://...",
  "decks": [
    {
      "deck_name": "4C Rhinos",
      "archetype": "Midrange",
      "mainboard": [{"name": "Murktide Regent", "quantity": 4, ...}],
      "sideboard": [...],
      "stats": {
        "win_rate": 0.542,
        "metagame_share": 0.123,
        "sample_size": 1847
      },
      "tournament_info": {
        "event_type": "Modern Challenge",
        "date": "YYYY-MM-DD",
        "placement": 5
      }
    }
  ]
}
```

#### 4. meta/current.json - 当前环境Meta
```json
{
  "generated_date": "YYYY-MM-DD",
  "based_on_ban_list_date": "YYYY-MM-DD",
  "data_period": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "top_decks": [...],
  "meta_composition": {
    "aggro": 0.35,
    "control": 0.15,
    "midrange": 0.25,
    "combo": 0.15,
    "other": 0.10
  },
  "coverage_rate": 0.72,
  "total_decks_analyzed": 5420
}
```

#### 5. cards/ - 卡牌数据（Scryfall API + 本地缓存）
- **策略**：不维护全量本地卡牌数据库，按需通过Scryfall API查询
- **缓存机制**：查询结果缓存到 `cards/cache/` 目录，避免重复请求
- **缓存Schema** (`cards/cache/{card_name_slug}.json`)：
```json
{
  "name": "Murktide Regent",
  "mana_cost": "{U}{U}",
  "cmc": 2,
  "type_line": "Creature — Dragon",
  "colors": ["U"],
  "power": "6",
  "toughness": "6",
  "oracle_text": "...",
  "legalities": {
    "modern": "legal"
  },
  "cached_at": "YYYY-MM-DDTHH:mm:ssZ"
}
```

#### 6. user/preferences.json - 用户偏好
```json
{
  "user_id": "uuid",
  "preferred_archetypes": ["Aggro", "Control"],
  "avoided_cards": ["Splinter Twin"],
  "budget": "medium",
  "communication_style": "detailed",
  "created_at": "YYYY-MM-DDTHH:mm:ssZ",
  "updated_at": "YYYY-MM-DDTHH:mm:ssZ"
}
```

## 注意事项
- 禁牌表更新频率：通常随新系列发售或紧急禁令，TIMELINE需在 `build_banlist_snapshots.py` 中手动维护
- 数据时效性：使用当前Meta周期内的比赛数据（由 `meta.json` 中 `current_period` 界定）
- 数据文件采用JSON格式，便于后续解析和版本控制
- 卡牌数据不维护全量本地库，通过Scryfall API按需查询+本地缓存
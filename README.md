# MTG Modern Deckbuilder Agent

一个 **万智牌摩登赛制（Modern）** 的本地化组牌专家 Agent：以 **禁牌表周期（ban period）** 为时间轴，爬取赛事套牌数据，融合多源信息评估套牌强度与 Meta 结构，并基于用户目标给出组牌建议。

完整设计见 [`SPEC.md`](./SPEC.md)，项目内 Agent 运行规范见 [`docs/agent-prompt.md`](./docs/agent-prompt.md)。

---

## 核心特性

- **周期感知（period-aware）** — 严格按 B&R 公告划分 Meta 周期，不跨周期混合数据；周期信息见 `mtg_modern_data/ban_list/meta.json`。
- **多源融合** — MTGTop8（archetype 预分类、全量列表）+ MTGGoldfish（名次、key_cards、平台分项），按权重融合，抑制 MTGO League 选择偏差。
- **赛事级别加权** — Professional / Major / Competitive / Regular 四级权重，有效样本量按权重累计而非简单计数。
- **强度评分** — `meta_share + perf_score + consistency + power_density + tournament_win` 五个维度打分并分 Tier。
- **Meta 组合** — 统计快攻/控制/中速/Combo 比例、Top N 覆盖率、构建对阵矩阵（heuristic，明确标注）。
- **组牌建议** — 根据 `archetype` + `gameplan` + `power_level`（及可选的 `target_matchups` / `avoid_cards` / `preferred_colors`）生成主备牌结构。

## 数据来源

| 来源 | 状态 | 用途 |
|------|------|------|
| MTGTop8 | ✅ 主用 | 全量 decklists、archetype 预分类 |
| MTGGoldfish | ✅ 主用 | decklists、metagame、placements、key_cards |
| Scryfall API | ✅ 按需 | 卡牌规则 / 费用 / 合法性查询（不维护本地全量库） |
| MTGO 官方 Decklists | 🔜 候选 | 高质量样本补充 |
| TopDeck.gg API | 🔜 PoC | round-level 结构化数据 |
| ~~Melee.gg~~ | ❌ 已移除 | 网络/VPN 依赖强、维护成本高 |

## 快速开始

### 环境

- Python 3（脚本使用 `argparse` / `requests` / `beautifulsoup4` / 标准库）
- 安装依赖（建议用 venv）：

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install requests beautifulsoup4 lxml
  ```

### 主流水线

按以下顺序执行，更新本地数据并生成评估产物：

```bash
python3 scrape_decklists_top8.py --max-events 999
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap
python3 evaluate_deck_strength.py --top 15
python3 scripts/build_card_impact.py
python3 compose_meta.py
```

也可用统一编排脚本一次性跑完一个周期：

```bash
python3 scripts/fetch_period_data.py --start YYYY-MM-DD --end YYYY-MM-DD
```

### 关键产物

| 文件 | 内容 |
|------|------|
| `mtg_modern_data/ban_list/current.json` | 当前禁牌表 |
| `mtg_modern_data/ban_list/meta.json` | 全部历史周期 + 当前周期元数据 |
| `mtg_modern_data/decks/processed/fused_archetypes.json` | 多源融合后的全量 archetype（含 key_cards / consistency / power_density） |
| `mtg_modern_data/decks/top_n/top_decks.json` | Top N 套牌排名 |
| `mtg_modern_data/cards/card_impact.json` | 单卡影响度 |
| `mtg_modern_data/meta/current.json` | 当前周期 Meta 快照（结构 + 角色 + 对阵矩阵） |
| `mtg_modern_data/decks/reports/` | 周期报告（HTML / JSON） |

### 测试

```bash
python3 -m pytest
```

测试覆盖周期工具、Goldfish 搜索 URL、MTGO 分类器、评估流水线集成等。

## 目录结构

```
.
├── SPEC.md                       # 完整设计规格
├── docs/
│   ├── agent-prompt.md           # Agent 运行时行为规范
│   ├── next-data-source-plan.md  # 数据源 PoC 路线图
│   └── superpowers/              # 内部 spec / plan 记录
├── mtg_modern_data/              # 本地数据湖（核心产物）
│   ├── ban_list/                 # 禁牌表 + 历史快照
│   ├── cards/                    # 卡牌影响度等
│   ├── decks/                    # raw / processed / top_n / reports
│   ├── meta/                     # Meta 快照 + 历史
│   ├── schemas/                  # JSON Schema
│   ├── sources/                  # 外部源缓存
│   └── user/                     # 用户输入与生成建议
├── scripts/                      # 辅助 / 编排脚本
├── tests/                        # pytest 套件
├── scrape_decks_mtgtop8.py       # Top8 套牌爬虫
├── scrape_goldfish_two_phase.py  # Goldfish 两阶段爬虫
├── scrape_decks_goldfish.py      # Goldfish 聚合爬虫
├── evaluate_deck_strength.py     # 强度评估
├── compose_meta.py               # Meta 组合
└── build_banlist_snapshots.py    # 禁牌表快照生成
```

## 可用 Skills

项目内提供以下 Claude Code skills，可在对话中按需触发：

- **top8-scraper** — MTGTop8 数据爬取 / 调试 / 校验
- **goldfish-scraper** — MTGGoldfish 数据爬取 / 调试 / 校验
- **card-impact** — 单卡影响度、archetype 核心卡、禁/解禁冲击
- **mtg-banlist** — 当前禁牌、禁牌历史、B&R 生效日、当前周期

## 设计原则

1. **尊重当前周期** — 任何分析都以 `meta.json.current_period` 为准；不同周期数据不混合。
2. **可观察 > 启发式** — 真实数据优于估算；启发式结果必须显式标注（如 `source: "heuristic"`）。
3. **决定性优于 ad hoc** — 优先使用本地结构化数据和确定性脚本，不靠临时推断。
4. **数据源诚信** — 不引入已弃用源；新源需先过 PoC 验证再纳入主流水线。
5. **选择偏差显式处理** — MTGO League 占 Goldfish 样本 ~60% 但偏差严重，按 `(1 - 0.35)` 修正。

## 路线图

- 接入 **TopDeck.gg API**（round-level match 数据）— 替换当前 heuristic 对阵矩阵
- 评估 **MTGO 官方 Decklists** / **MTGDecks.net** / **Magic: The Metagame** 作为校验源
- 推进 **组牌建议** 的端到端实现（Phase 5）

## 许可

本仓库为个人研究项目，未声明开源许可；如需复用请先联系作者。

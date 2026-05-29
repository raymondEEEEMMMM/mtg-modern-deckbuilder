---
name: goldfish-scraper
description: MTGGoldfish Modern format tournament decklist scraper. This skill should be used when the user needs to scrape, debug, optimize, or test the Goldfish decklist scraper. Covers two-phase Playwright scraping with Cloudflare bypass, incremental save, period-aware filtering, Top8 overlap detection, and data pipeline integration. Triggers on: running the Goldfish scraper, fixing scraper errors, adding new features to the scraper, analyzing scraped decklist data, or integrating Goldfish data with the evaluation pipeline.
---

# Goldfish Scraper Skill

## Overview

Scrape complete 75-card decklists from MTGGoldfish Modern tournaments using Playwright. The scraper supplements MTGTop8 data (primary source) with Goldfish-only decklists, using overlap detection to avoid duplicates. Outputs feed into `evaluate_deck_strength.py` for the deck strength evaluation pipeline.

Canonical implementation lives in the project root. Bundled files under this
skill are mirrors for reference and must be kept in sync after scraper edits.

## ⚠️ CRITICAL: Period-Aware Scraping

**抓取范围必须限定在当前 Meta 周期内。** 这是最重要的规则。

### 什么是 Meta 周期？

一个 Meta 周期 = 两次相邻 B&R（禁牌表）更新之间的时间段。周期以禁牌表生效日期命名。

- 周期起始日期由 `mtg_modern_data/ban_list/meta.json` 中 `changes_history` 最后一项的 `effective_date` 决定
- 当前周期：**2026-05-18** 起（最近一次 B&R 更新）
- 脚本 `scrape_goldfish_two_phase.py` 自动从 `meta.json` 读取 `PERIOD_START`

### 周期过滤规则

1. **只抓取赛事日期 >= PERIOD_START 的赛事**
2. 日期 < PERIOD_START 的赛事标记为 `skipped_out_of_period`，不抓取
3. 搜索 URL 的日期范围必须从 PERIOD_START 开始（不是随意设定）
4. 已抓取的非周期内数据必须从 decklist 输出文件中清除

### 为什么必须限制在周期内？

- 不同周期的禁牌表不同，混用数据会导致合法性判断错误
- Meta 环境在 B&R 更新后剧变，旧数据不具有参考价值
- 评估管线依赖周期内数据做统计分析

### 代码中的实现

```python
# scrape_goldfish_two_phase.py 自动读取周期起始
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
PERIOD_START = "2026-05-18"  # fallback
if META_FILE.exists():
    _meta = json.load(open(META_FILE))
    PERIOD_START = _meta["changes_history"][-1]["effective_date"]

# Phase 1: 构建搜索 URL 时使用周期起始
search_url = GOLDFISH_TOURNAMENT_SEARCH_URL.format(
    start=PERIOD_START.replace("-", "%2F"),
    end=today.replace("-", "%2F")
)

# Phase 2: 过滤非周期内赛事
for t in tournaments:
    if t["date"] < PERIOD_START:
        t["status"] = "skipped_out_of_period"
```

### 修改/运行时检查清单

- [ ] 确认 `meta.json` 中 `changes_history` 最后一项的 `effective_date`
- [ ] 搜索 URL 的 date_range 起始日期 = PERIOD_START
- [ ] 非 League 赛事中，日期 < PERIOD_START 的已标记为 `skipped_out_of_period`
- [ ] 输出文件中不包含周期外的 decklist 数据
- [ ] 如果 B&R 刚更新，需重新运行 Phase 1 刷新赛事索引

## Quick Start

Run the **two-phase** scraper (recommended):

```bash
cd /Users/lianghaoming/mtg_agents_workplace

# Phase 1+2: Full scrape (auto-detects period start from meta.json)
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap

# Limit number of tournaments
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap --max-tournaments 5
```

If interrupted, resume with `--resume` — completed tournaments are skipped.

After scraping, run evaluation:

```bash
python3 evaluate_deck_strength.py --top 15
python3 scripts/build_card_impact.py
python3 compose_meta.py
```

## CLI Arguments

| Argument | Description |
|---|---|
| `--max-tournaments N` | Limit number of tournaments to scrape (default: 999) |
| `--skip-top8-overlap` | Filter out decks already in Top8 data (by archetype+player) |
| `--resume` | Skip already-scraped tournaments, continue from last save |

## Architecture

### Two-Phase Design

The current scraper uses a two-phase approach to avoid triggering DDoS detection:

**Phase 1: Tournament Index**
1. Navigate to Goldfish tournament search page
2. Extract all tournament links across all pages
3. Save as `goldfish_tournament_index.json` with status tracking
4. Filter out League events and out-of-period tournaments

**Phase 2: Incremental Decklist Scrape**
1. For each pending tournament in the index:
   - Load tournament page
   - Click "Expand Decks" to expand all decklists at once
   - Scroll down to trigger lazy loading
   - Parse all expanded decklists in one pass
   - If empty decklists remain, click individual "Expand" links as fallback
   - Save progress incrementally
2. Mark completed tournaments in index
3. On resume, skip completed/failed/skipped tournaments

### Data Flow

```
scrape_goldfish_two_phase.py
  → mtg_modern_data/decks/raw/decklists/goldfish_tournament_index.json  (Phase 1)
  → mtg_modern_data/decks/raw/decklists/{date}_goldfish_decklists.json  (Phase 2)
  → (merged with Top8 decklists in evaluate_deck_strength.py)
  → mtg_modern_data/decks/processed/fused_archetypes.json
  → mtg_modern_data/decks/top_n/top_decks.json
  → scripts/build_card_impact.py
  → mtg_modern_data/cards/card_impact.json
  → compose_meta.py
  → mtg_modern_data/meta/current.json
```

### Key Design Decisions

1. **Period-aware** — only scrape tournaments within current Meta period (from `meta.json`)
2. **Top8 is primary, Goldfish supplements** — never duplicate existing data
3. **Two-phase** — separate index collection from decklist scraping; prevents DDoS detection
4. **Expand all at once** — click "Expand Decks" then scroll to lazy-load all decklists
5. **Incremental save** — progress saved after each tournament, crash-safe
6. **Status tracking** — each tournament has status: `pending` / `completed` / `failed` / `skipped` / `skipped_out_of_period`
7. **Two-level dedup**:
   - Scraper: `--skip-top8-overlap` by (archetype, player)
   - Evaluator: merge-time dedup by (event, player) and (archetype, player)

### Decklist Parsing (Two Methods)

1. **Primary**: `data-card-name` attributes on `<tr>` rows (most reliable)
2. **Fallback**: Text content parsing from `.deck-view-deck-table` innerText

Both methods detect maindeck/sideboard boundary via `<th>Sideboard</th>`.

## Testing & Debugging Workflow

### Step 1: Quick Smoke Test

```bash
python3 scrape_goldfish_two_phase.py --max-tournaments 1 --skip-top8-overlap
```

Verify:
- Browser opens (non-headless)
- Cloudflare challenge resolves (may need manual CAPTCHA)
- 1 tournament scraped with decklists (all 60+15, not 0+0)
- Output file created at `mtg_modern_data/decks/raw/decklists/`
- Tournament index shows correct `status`

### Step 2: Verify Period Filtering

```bash
python3 -c "
import json
with open('mtg_modern_data/ban_list/meta.json') as f:
    meta = json.load(f)
period_start = meta['changes_history'][-1]['effective_date']
print(f'Current period starts: {period_start}')

with open('mtg_modern_data/decks/raw/decklists/goldfish_tournament_index.json') as f:
    idx = json.load(f)
out_of_period = [t for t in idx['tournaments'] if t['date'] < period_start and t['status'] != 'skipped_out_of_period']
if out_of_period:
    print(f'WARNING: {len(out_of_period)} tournaments before period start not filtered!')
    for t in out_of_period:
        print(f'  {t[\"tournament_id\"]} | {t[\"date\"]} | {t[\"status\"]}')
else:
    print('OK: All pre-period tournaments are skipped')
"
```

### Step 3: Check Output Quality

```bash
python3 -c "
import json
with open('mtg_modern_data/decks/raw/decklists/2026-05-28_goldfish_decklists.json') as f:
    data = json.load(f)
print(f'Total: {data[\"total_decklists\"]}')
# Check for 0+0 decklists (parsing failure)
bad = [d for d in data['decklists'] if d['maindeck_count'] == 0]
if bad:
    print(f'WARNING: {len(bad)} decklists with 0 maindeck cards!')
else:
    print('OK: All decklists have cards')

# Verify no out-of-period data
with open('mtg_modern_data/ban_list/meta.json') as f:
    period_start = json.load(f)['changes_history'][-1]['effective_date']
from datetime import datetime
oop = [d for d in data['decklists'] if d.get('event_date','') < period_start]
if oop:
    print(f'WARNING: {len(oop)} decklists from before period start!')
else:
    print('OK: All decklists within period')
"
```

### Step 4: Full Run

```bash
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap
```

### Step 5: Run Evaluation

```bash
python3 evaluate_deck_strength.py --top 15
```

## Common Issues

For detailed troubleshooting, see `references/troubleshooting.md`.

| Issue | Fix |
|---|---|
| Cloudflare timeout | Must run non-headless; go directly to search URL, not homepage |
| Stale .pyc cache | `find . -name "__pycache__" -exec rm -rf {} +` |
| Playwright not found | `python3 -m playwright install chromium` |
| Empty decklists (0+0) | "Expand Decks" didn't lazy-load all; script now scrolls page after expanding |
| Duplicate data | Always use `--skip-top8-overlap`; evaluator has second dedup layer |
| Out-of-period data | Check `meta.json` period start; ensure search URL starts from that date |
| League events in output | Script auto-filters by `is_league` flag; Leagues have no placement data |

## Modifying the Scraper

When editing `scrape_goldfish_two_phase.py`:

1. **NEVER remove period filtering** — all data must be within current Meta period
2. **Never add homepage navigation** — Cloudflare blocks it
3. **Always test with `--max-tournaments 1`** before full runs
4. **Preserve incremental save** — progress saved after each tournament
5. **Keep `GOLDFISH_TO_CANONICAL` in sync** with `evaluate_deck_strength.py` mapping
6. **When B&R updates** — re-run Phase 1 to refresh index with new period start
7. **Update this skill's script mirrors** after root-script changes:
   `cp scrape_goldfish_two_phase.py .codebuddy/skills/goldfish-scraper/scripts/scrape_goldfish_two_phase.py`

## Tournament Index Status Values

| Status | Meaning |
|---|---|
| `pending` | Not yet scraped, will be processed |
| `completed` | Successfully scraped |
| `failed` | Scraping failed, will be retried on next run |
| `skipped` | League event, automatically skipped |
| `skipped_out_of_period` | Tournament date before current Meta period |

## Resources

### scripts/
- `scrape_goldfish_two_phase.py` — the current two-phase scraper (recommended)

### references/
- `troubleshooting.md` — detailed debugging guide, page structure reference, data pipeline docs

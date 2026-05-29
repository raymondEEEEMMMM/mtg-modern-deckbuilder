---
name: top8-scraper
description: MTGTop8 Modern format tournament decklist scraper. This skill should be used when the user needs to scrape, debug, optimize, or test the Top8 decklist scraper. Covers Playwright-based scraping with rate limiting, period-aware filtering, banlist legality validation, and data pipeline integration. Triggers on: running the Top8 scraper, fixing scraper errors, adding new features to the scraper, analyzing scraped decklist data, or integrating Top8 data with the evaluation pipeline.
---

# Top8 Scraper Skill

## Overview

Scrape complete 75-card decklists from MTGTop8 Modern tournaments using Playwright. MTGTop8 is the **primary data source** for the deck evaluation pipeline — Goldfish data supplements it. Each decklist is validated against the current Modern banlist. The scraper is simpler than the Goldfish scraper (no Cloudflare protection, no two-phase design), but must still respect period boundaries.

Canonical implementation lives in the project root. Bundled files under this
skill are mirrors for reference and must be kept in sync after scraper edits.

## ⚠️ CRITICAL: Period-Aware Scraping

**抓取范围必须限定在当前 Meta 周期内。** 这是最重要的规则。

### 什么是 Meta 周期？

一个 Meta 周期 = 两次相邻 B&R（禁牌表）更新之间的时间段。周期以禁牌表生效日期命名。

- 周期起始日期由 `mtg_modern_data/ban_list/meta.json` 中 `changes_history` 最后一项的 `effective_date` 决定
- 当前周期：**2026-05-18** 起（最近一次 B&R 更新）
- 脚本自动从 `meta.json` 读取 `PERIOD_START`

### 周期过滤规则

1. **只抓取赛事日期 >= PERIOD_START 的赛事**
2. 日期 < PERIOD_START 的赛事跳过（脚本中已有此逻辑）
3. 输出文件中 `period_start` 字段记录周期起始日期
4. **当 B&R 更新后**，需重新抓取以覆盖新周期

### 代码中的实现

```python
# scrape_decklists_top8.py 自动读取周期起始
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
PERIOD_START = "2026-05-18"  # fallback
if META_FILE.exists():
    _meta = json.load(open(META_FILE))
    PERIOD_START = _meta["changes_history"][-1]["effective_date"]

# 赛事日期过滤
if event_date < PERIOD_START:
    print(f"  Skipping (before {PERIOD_START})")
    continue
```

### 修改/运行时检查清单

- [ ] 确认 `meta.json` 中 `changes_history` 最后一项的 `effective_date`
- [ ] 赛事日期 < PERIOD_START 的已正确跳过
- [ ] 输出文件中不包含周期外的 decklist 数据
- [ ] 如果 B&R 刚更新，需重新运行抓取

## Two Scripts

### 1. `scrape_decklists_top8.py` — Full Decklist Scraper (Primary)

Scrapes complete 75-card decklists from MTGTop8 events.

```bash
cd /Users/lianghaoming/mtg_agents_workplace

# Full scrape
python3 scrape_decklists_top8.py --max-events 999

# Quick test
python3 scrape_decklists_top8.py --max-events 2
```

#### CLI Arguments

| Argument | Description |
|---|---|
| `--max-events N` | Limit number of events to scrape (default: 999) |
| `--skip-existing` | Skip already-scraped events (planned, not yet implemented) |

#### Output File

`mtg_modern_data/decks/raw/decklists/{date}_top8_decklists.json`

#### Output Schema

```json
{
  "format": "Modern",
  "collected_date": "2026-05-28",
  "source": "MTGTop8",
  "period_start": "2026-05-18",
  "total_decks": 153,
  "legal_decks": 153,
  "illegal_decks": 0,
  "legality_report": {
    "legal": 153,
    "illegal": 0,
    "illegal_decks": []
  },
  "decklists": [
    {
      "source": "mtgtop8",
      "event_id": "85677",
      "event_name": "MTGO Modern Challenge 64",
      "event_date": "27/05/26",
      "deck_id": "850915",
      "deck_name": "Boros Aggro",
      "player": "Mayodominaria",
      "maindeck": [{"qty": 4, "name": "Ragavan, Nimble Pilferer"}, ...],
      "sideboard": [{"qty": 2, "name": "Unlucky Witness"}, ...],
      "maindeck_count": 60,
      "sideboard_count": 15,
      "legality": {"legal": true, "banned_cards": []}
    }
  ]
}
```

### 2. `scrape_decks_mtgtop8.py` — Archetype Aggregation Scraper (Supplementary)

Scrapes archetype-level aggregation data (metagame shares, tournament tier weighting). Also reads period from `meta.json`.

```bash
python3 scrape_decks_mtgtop8.py [--period YYYY-MM-DD] [--dry-run]
```

This is used for the metagame snapshot, not for individual decklists.

## Architecture

### Data Flow

```
scrape_decklists_top8.py        (Primary: full 75-card decklists)
  → mtg_modern_data/decks/raw/decklists/{date}_top8_decklists.json

scrape_decks_mtgtop8.py         (Supplementary: archetype aggregation)
  → mtg_modern_data/decks/raw/{date}_mtgtop8.json

evaluate_deck_strength.py       (merge Top8 + Goldfish)
  → mtg_modern_data/decks/processed/fused_archetypes.json
  → mtg_modern_data/decks/top_n/top_decks.json
  → scripts/build_card_impact.py
  → mtg_modern_data/cards/card_impact.json
  → compose_meta.py
  → mtg_modern_data/meta/current.json
```

### Key Design Decisions

1. **Period-aware** — only scrape tournaments within current Meta period (from `meta.json`)
2. **Primary data source** — Top8 decklists are the main input for evaluation; Goldfish supplements
3. **Banlist validation** — every decklist checked against `current.json`; illegal decks flagged but still saved
4. **Rate limiting** — 0.3s/deck, 1s/event (MTGTop8 has lighter anti-bot than Goldfish)
5. **Headless OK** — MTGTop8 doesn't use Cloudflare, headless mode works fine
6. **No incremental save** — script runs to completion; if interrupted, must re-run (TODO: add `--resume`)

### Scraper Workflow

1. **Get event links** — visit MTGTop8 Modern format page, extract `event?e=` links
2. **For each event**:
   a. Load event page, extract metadata (name, date, player count)
   b. Filter by date — skip if before `PERIOD_START`
   c. Extract deck links (`d=` parameter)
   d. For each deck: visit deck page → parse MD + SIDEBOARD sections
   e. Validate against banlist
3. **Save results** — single JSON output file

### Decklist Parsing

MTGTop8 deck pages use a text-based format:
- Cards listed as `4 Card Name` (quantity + name)
- `MD` marks the maindeck section start
- `SIDEBOARD` marks the sideboard section
- Category headers like `LANDS (23)`, `CREATURES (22)` are automatically skipped

## Testing & Debugging Workflow

### Step 1: Quick Smoke Test

```bash
python3 scrape_decklists_top8.py --max-events 2
```

Verify:
- Headless browser opens and scrapes 2 events
- Decklists have 60+15 cards (not 0+0)
- Output file created at `mtg_modern_data/decks/raw/decklists/`

### Step 2: Verify Period Filtering

```bash
python3 -c "
import json
with open('mtg_modern_data/ban_list/meta.json') as f:
    meta = json.load(f)
period_start = meta['changes_history'][-1]['effective_date']
print(f'Current period starts: {period_start}')

import glob
files = sorted(glob.glob('mtg_modern_data/decks/raw/decklists/*_top8_decklists.json'), reverse=True)
if files:
    with open(files[0]) as f:
        data = json.load(f)
    print(f'Output period_start: {data.get(\"period_start\")}')
    # Check all event dates are within period
    oop = [d for d in data['decklists']
           if d.get('event_date') and
           f'20{d[\"event_date\"].split(\"/\")[2]}-{d[\"event_date\"].split(\"/\")[1]}-{d[\"event_date\"].split(\"/\")[0]}' < period_start]
    if oop:
        print(f'WARNING: {len(oop)} decklists from before period start!')
    else:
        print('OK: All decklists within period')
"
```

### Step 3: Check Output Quality

```bash
python3 -c "
import json, glob
files = sorted(glob.glob('mtg_modern_data/decks/raw/decklists/*_top8_decklists.json'), reverse=True)
if files:
    with open(files[0]) as f:
        data = json.load(f)
    print(f'Total: {data[\"total_decks\"]} | Legal: {data[\"legal_decks\"]} | Illegal: {data[\"illegal_decks\"]}')
    bad = [d for d in data['decklists'] if d['maindeck_count'] == 0]
    if bad:
        print(f'WARNING: {len(bad)} decklists with 0 maindeck cards!')
    else:
        print('OK: All decklists have cards')
"
```

### Step 4: Full Run

```bash
python3 scrape_decklists_top8.py --max-events 999
```

### Step 5: Run Evaluation

```bash
python3 evaluate_deck_strength.py --top 15
```

## Common Issues

For detailed troubleshooting, see `references/troubleshooting.md`.

| Issue | Fix |
|---|---|
| Playwright not found | `python3 -m playwright install chromium` |
| Stale .pyc cache | `find . -name "__pycache__" -exec rm -rf {} +` |
| Empty decklists | Check page structure; category headers may have changed |
| Out-of-period data | Check `meta.json` period start; script auto-filters by date |
| Illegal decks in output | Normal — these are flagged but still saved for reference |

## Modifying the Scraper

When editing `scrape_decklists_top8.py`:

1. **NEVER remove period filtering** — all data must be within current Meta period
2. **Keep `CATEGORY_HEADERS` regex up to date** — MTGTop8 may change card category names
3. **Always test with `--max-events 2`** before full runs
4. **Consider adding `--resume` support** — currently no incremental save
5. **Update this skill's script mirrors** after root-script changes:
   `cp scrape_decklists_top8.py .codebuddy/skills/top8-scraper/scripts/scrape_decklists_top8.py`
   and `cp scrape_decks_mtgtop8.py .codebuddy/skills/top8-scraper/scripts/scrape_decks_mtgtop8.py`

## Relationship with Goldfish Scraper

| Aspect | Top8 Scraper | Goldfish Scraper |
|---|---|---|
| Role | **Primary data source** | Supplementary source |
| Anti-bot | Light (no Cloudflare) | Heavy (Cloudflare) |
| Headless | Works fine | Must be non-headless |
| Incremental | Not yet | Yes (two-phase) |
| Period-aware | Yes (from `meta.json`) | Yes (from `meta.json`) |
| Dedup | N/A (primary) | `--skip-top8-overlap` |

## Resources

### scripts/
- `scrape_decklists_top8.py` — full decklist scraper (primary)
- `scrape_decks_mtgtop8.py` — archetype aggregation scraper (supplementary)

### references/
- `troubleshooting.md` — detailed debugging guide

# Goldfish Scraper Troubleshooting Reference

## Known Issues & Solutions

### 1. Cloudflare Challenge
- **Symptom**: `Page.goto: Timeout 60000ms exceeded` or page shows "请稍候" / "Just a moment"
- **Cause**: MTGGoldfish uses Cloudflare bot protection; detects automated browsers via CDP
- **Fix (priority order)**:
  1. **Use real Chrome + user profile** — `channel="chrome"` in Playwright `launch_persistent_context` with `--user-data-dir` pointing to real Chrome profile (most reliable)
  2. NEVER use headless mode — must run with `headless=False`
  3. NEVER navigate to homepage first — go directly to tournament search URL
  4. `navigate_with_retry()` handles automatic retry with exponential backoff
  5. If still blocked: close all browsers, wait 5+ minutes for Cloudflare to cool down, then retry
  6. **Don't launch too many browser instances in short time** — Cloudflare rate-limits by IP

### 2. Out-of-Period Data (CRITICAL)
- **Symptom**: Decklists from before the current Meta period appear in output
- **Cause**: Search URL date range starts too early, or index contains pre-period tournaments
- **Fix**:
  1. Check `mtg_modern_data/ban_list/meta.json` → `changes_history`[-1] → `effective_date` for current period start
  2. Ensure search URL `date_range` starts from that date
  3. All tournaments with `date < PERIOD_START` should have `status: "skipped_out_of_period"` in index
  4. Remove out-of-period decklists from output file (filter by `event_id` or `event_date`)
  5. **When B&R updates**: re-run Phase 1 to rebuild index with new period start

### 3. Stale .pyc Cache
- **Symptom**: Running script shows old code behavior (e.g., navigating to homepage)
- **Cause**: Python caches compiled bytecode in `__pycache__/`
- **Fix**: `find . -name "__pycache__" -exec rm -rf {} + && find . -name "*.pyc" -delete`

### 4. Playwright Browser Not Found
- **Symptom**: `playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist`
- **Fix**: `python3 -m playwright install chromium`

### 5. Empty Decklists (0+0 cards)
- **Symptom**: deck parsed with `maindeck_count: 0` and `sideboard_count: 0`
- **Cause**:
  - "Expand Decks" button clicked but decklists not lazy-loaded (need scrolling)
  - Individual deck-tab container not expanded
- **Fix**:
  - After clicking "Expand Decks", scroll the page to trigger lazy loading
  - For remaining 0+0 decks, click individual "Expand" links as fallback
  - The two-phase script handles this automatically

### 6. Duplicate Decklists
- **Symptom**: Same deck appears multiple times
- **Prevention**:
  - `--skip-top8-overlap`: filters decks already in Top8 data by (archetype, player)
  - `--resume`: skips already-scraped tournaments
  - Dedup by `deck_id` within each tournament
  - `evaluate_deck_strength.py` does additional merge-time dedup by (event, player) and (archetype, player)

### 7. Two-Phase Script: Tournament Index Out of Sync
- **Symptom**: Index shows tournaments that no longer exist, or new tournaments not in index
- **Fix**: Delete `goldfish_tournament_index.json` and re-run Phase 1

## Page Structure Reference

### Tournament Search Page
- URL: `https://www.mtggoldfish.com/tournament_searches/create?...`
- Tournament links: `a[href*="/tournament/"]`
- League events contain "League" in name — skip these (5-0 only, no placement data)
- Pagination: `a[href*='page=N']` links at bottom

### Tournament Detail Page
- Deck rows: `table tbody tr` with cells: [date, archetype_link, format, deck_count]
- Deck IDs: extracted from `a[href*="/deck/"]` href
- "Expand Decks" link: expands all decklists at once (preferred)
- Individual "Expand" links: per-deck fallback

### Expanded Decklist
- Container: `[id*="deck-{deck_id}-tab"]`
- Card table: `.deck-view-deck-table`
- Card rows: `tr[data-card-name]` with `td` for quantity
- Sideboard starts after `<th>Sideboard</th>`

## Archetype Name Mapping

Goldfish uses different names than MTGTop8. The `GOLDFISH_TO_CANONICAL` dict maps them:
- "Izzet Affinity" → "Affinity"
- "Izzet Prowess" → "UR Prowess"
- "Belcher" → "Landless"
- "4c Energy" → "Boros Energy"
- "Boros Burn" → "Red Deck Wins"
- "Domain Zoo" → "4/5c Aggro"
- "Gruul Basking Broodscale Combo" → "Broodscale Bloodchief"
- See full mapping in `scripts/scrape_goldfish_two_phase.py`

## Data Pipeline

```
scrape_goldfish_two_phase.py
  → mtg_modern_data/decks/raw/decklists/goldfish_tournament_index.json  (Phase 1 index)
  → mtg_modern_data/decks/raw/decklists/{date}_goldfish_decklists.json  (Phase 2 decklists)
                                       ↓
evaluate_deck_strength.py     ←  (merge with Top8 decklists)
                                       ↓
                              →  mtg_modern_data/decks/processed/fused_archetypes.json
                              →  mtg_modern_data/decks/top_n/top_decks.json
```

## Period-Aware Data Validation

Always verify after scraping:

```python
import json
from pathlib import Path

# Get current period start
with open('mtg_modern_data/ban_list/meta.json') as f:
    period_start = json.load(f)['changes_history'][-1]['effective_date']
print(f'Period starts: {period_start}')

# Check index
with open('mtg_modern_data/decks/raw/decklists/goldfish_tournament_index.json') as f:
    idx = json.load(f)
bad = [t for t in idx['tournaments']
       if t['date'] < period_start and t['status'] not in ('skipped_out_of_period', 'skipped')]
if bad:
    print(f'WARNING: {len(bad)} out-of-period tournaments not filtered!')
else:
    print('OK: Index is clean')

# Check decklists
decklist_file = Path('mtg_modern_data/decks/raw/decklists')
files = sorted(decklist_file.glob('*_goldfish_decklists.json'), reverse=True)
if files:
    with open(files[0]) as f:
        data = json.load(f)
    bad_dl = [d for d in data['decklists'] if d.get('maindeck_count', 0) == 0]
    print(f'Decklists: {len(data["decklists"])} total, {len(bad_dl)} with 0 cards')
```

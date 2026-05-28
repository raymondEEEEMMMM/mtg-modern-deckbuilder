# Top8 Scraper Troubleshooting Reference

## Known Issues & Solutions

### 1. Out-of-Period Data (CRITICAL)
- **Symptom**: Decklists from before the current Meta period appear in output
- **Cause**: `PERIOD_START` not read from `meta.json`, or script run with wrong date
- **Fix**:
  1. Check `mtg_modern_data/ban_list/meta.json` → `changes_history`[-1] → `effective_date` for current period start
  2. Script auto-reads this value; verify with `print(f"Period start: {PERIOD_START}")` at startup
  3. All events with `date < PERIOD_START` are skipped during scraping
  4. If B&R just updated, re-run scraper to collect new period data

### 2. Empty Decklists (0 cards)
- **Symptom**: deck parsed with `maindeck_count: 0` and `sideboard_count: 0`
- **Cause**:
  - Page didn't load fully
  - Deck page structure changed (no "MD" section found)
- **Fix**:
  - Increase `time.sleep` after page load
  - Check if MTGTop8 changed their HTML structure
  - The script uses `document.body.innerText` to find "MD " section

### 3. Category Headers Not Filtered
- **Symptom**: Cards like "LANDS (23)" or "CREATURES (22)" appear in decklists
- **Cause**: `CATEGORY_HEADERS` regex doesn't match new header format
- **Fix**: Update the regex pattern in `scrape_decklists_top8.py`:
  ```python
  CATEGORY_HEADERS = re.compile(
      r"^(LANDS|CREATURES|INSTANTS and SORC\.?|INSTANTS|SORC\.?|OTHER SPELLS|"
      r"ARTIFACTS|ENCHANTMENTS|PLANESWALKERS|SPELLS)"
      r"\s*\(\d+\)?$",
      re.IGNORECASE,
  )
  ```

### 4. Stale .pyc Cache
- **Symptom**: Running script shows old code behavior
- **Cause**: Python caches compiled bytecode in `__pycache__/`
- **Fix**: `find . -name "__pycache__" -exec rm -rf {} + && find . -name "*.pyc" -delete`

### 5. Playwright Browser Not Found
- **Symptom**: `playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist`
- **Fix**: `python3 -m playwright install chromium`

### 6. Event Date Parsing Errors
- **Symptom**: Valid recent events being skipped
- **Cause**: MTGTop8 uses `DD/MM/YY` format; script converts to `YYYY-MM-DD` for comparison
- **Fix**: Check date parsing logic:
  ```python
  parts = event_info["date"].split("/")
  event_date = f"20{parts[2]}-{parts[1]}-{parts[0]}"
  ```
  If MTGTop8 changes date format, update this parsing.

### 7. Illegal Decks in Output
- **Symptom**: Decks with banned cards appear in output
- **Cause**: This is expected behavior — illegal decks are saved but flagged
- **Note**: The `legality` field on each decklist indicates whether it's legal. Check `legality_report` at the top level for summary.

## Page Structure Reference

### MTGTop8 Modern Format Page
- URL: `https://www.mtgtop8.com/format?f=MO&meta=221`
- Event links: `a[href*="event?e="]`
- Contains paginated list of recent Modern events

### Event Page
- URL: `https://www.mtgtop8.com/event?e=XXXXX`
- Event name: `td.w_title` element
- Event date: `DD/MM/YY` format in page text
- Player count: `NNN players` in page text
- Deck links: `a[href*="d="]` with deck IDs

### Deck Page
- URL: `https://www.mtgtop8.com/event?d=XXXXX&...`
- Deck name and player: extracted from `<title>` (format: "DeckName - Player @ Event")
- Maindeck section starts after "MD " text
- Sideboard section starts after "SIDEBOARD" text
- Cards: "4 Card Name" format

## Archetype Name Differences

MTGTop8 and Goldfish use different archetype names. The `GOLDFISH_TO_CANONICAL` mapping in the Goldfish scraper normalizes them. Key differences:

| Top8 Name | Goldfish Name | Canonical |
|---|---|---|
| Boros Aggro | Boros Energy | Boros Energy |
| Izzet Prowess | Izzet Prowess | UR Prowess |
| Mono Red | Boros Burn | Red Deck Wins |
| Gruul Combo | Gruul Basking Broodscale Combo | Broodscale Bloodchief |

## Data Pipeline

```
scrape_decklists_top8.py  →  mtg_modern_data/decks/raw/decklists/{date}_top8_decklists.json
                                    ↓
evaluate_deck_strength.py  ←  (merge with Goldfish decklists)
                                    ↓
                           →  mtg_modern_data/decks/processed/fused_archetypes.json
                           →  mtg_modern_data/decks/top_n/top_decks.json
```

## Period-Aware Data Validation

Always verify after scraping:

```python
import json, glob

# Get current period start
with open('mtg_modern_data/ban_list/meta.json') as f:
    period_start = json.load(f)['changes_history'][-1]['effective_date']
print(f'Period starts: {period_start}')

# Check decklist output
files = sorted(glob.glob('mtg_modern_data/decks/raw/decklists/*_top8_decklists.json'), reverse=True)
if files:
    with open(files[0]) as f:
        data = json.load(f)
    print(f'Output period_start: {data.get("period_start")}')
    
    # Verify no out-of-period data
    oop = []
    for d in data['decklists']:
        ed = d.get('event_date', '')
        if ed:
            parts = ed.split('/')
            iso = f'20{parts[2]}-{parts[1]}-{parts[0]}'
            if iso < period_start:
                oop.append(d)
    
    if oop:
        print(f'WARNING: {len(oop)} decklists from before period start!')
        for d in oop[:5]:
            print(f'  {d["event_date"]} - {d["deck_name"]}')
    else:
        print('OK: All decklists within period')
```

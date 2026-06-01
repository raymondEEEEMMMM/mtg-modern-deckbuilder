---
name: top8-scraper
description: Use when scraping, debugging, or validating MTGTop8 Modern decklists and event data. Triggers include "scrape MTGTop8", "top8 decklists are stale", "MTGTop8 fetch failed", "rebuild top8 raw data", or whenever the agent needs to refresh the MTGTop8 portion of the local metagame dataset.
---

# MTGTop8 Scraper Skill

Scrape complete 75-card Modern decklists from MTGTop8 for the current ban
period. Each deck is checked against `mtg_modern_data/ban_list/current.json`
and tagged with legality status.

## Quick Start

```bash
# Full refresh of current period (default cap: 999 events)
python3 scrape_decklists_top8.py

# Cap event count for a quick smoke test
python3 scrape_decklists_top8.py --max-events 20

# Skip events whose decklist file already exists on disk
python3 scrape_decklists_top8.py --skip-existing
```

## CLI Flags

| Flag | Default | Purpose |
|---|---|---|
| `--max-events N` | `999` | Stop after N events. Useful for smoke tests. |
| `--skip-existing` | off | Skip events whose output JSON already exists in `decks/raw/decklists/`. |

There is no `--help`. The script uses positional `sys.argv` parsing.

## Data Flow

```text
MTGTop8 format/event/deck pages
  → playwright Chromium session
  → parse maindeck (60) + sideboard (15)
  → legality check vs ban_list/current.json
  → mtg_modern_data/decks/raw/decklists/YYYY-MM-DD_mtgtop8_decklists.json
```

The period start is auto-detected from
`mtg_modern_data/ban_list/meta.json` (`changes_history[].effective_date`,
latest entry). When the B&R changes, **re-run this scraper before running
`evaluate_deck_strength.py`**.

## Outputs

- `mtg_modern_data/decks/raw/decklists/*_mtgtop8_decklists.json` — one file
  per scrape run, full 75-card lists with legality status per deck.
- `mtg_modern_data/decks/raw/decklists/*_mtgtop8_illegal.json` — decks that
  failed the banlist check; kept for audit, not consumed by downstream
  evaluation.

## Pipeline Position

```bash
python3 scrape_decklists_top8.py --max-events 999     # 1. Top8 decklists
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap  # 2. Goldfish
python3 evaluate_deck_strength.py --top 15             # 3. Fuse + strength
python3 scripts/build_card_impact.py                   # 4. Card impact
python3 compose_meta.py                                # 5. Meta + matchup
```

Top8 and Goldfish are run sequentially because Goldfish uses
`--skip-top8-overlap` to avoid double-counting decks already captured here.

## Common Issues

- **Empty results**: site layout changed. Re-inspect the page selectors in
  `get_event_links`, `get_deck_links_from_event`, `scrape_decklist` (around
  `scrape_decklists_top8.py:150-310`).
- **All decks marked illegal**: `ban_list/current.json` is stale or empty.
  Use the `mtg-banlist` skill to refresh.
- **Playwright import error**: `pip install playwright` and
  `python -m playwright install chromium`.

## Cross-References

- **REQUIRED BACKGROUND:** Use `mtg-banlist` to verify the current period
  before scraping, and to confirm the legality of any decklist this skill
  flags as illegal.
- Companion: `goldfish-scraper` (same pipeline, second source).

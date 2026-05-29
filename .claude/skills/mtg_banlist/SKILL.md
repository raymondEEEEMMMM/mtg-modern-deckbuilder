---
name: mtg-banlist
description: MTG Modern banlist lookup and period-boundary skill. Use when the user asks about current banned cards, whether a card is legal in Modern, banlist history, B&R effective dates, or the current meta period used by the data pipeline.
---

# MTG Modern Banlist Skill

Search current and historical Modern banlist data from the local project cache.

## Quick Start

```bash
python3 .claude/skills/mtg_banlist/banlist_tool.py
python3 .claude/skills/mtg_banlist/banlist_tool.py Ponder
python3 .claude/skills/mtg_banlist/banlist_tool.py --history
python3 .claude/skills/mtg_banlist/banlist_tool.py --date 2026-05-18
python3 .claude/skills/mtg_banlist/banlist_tool.py --diff 2024-08-26
```

## Data Files

- `mtg_modern_data/ban_list/current.json`
- `mtg_modern_data/ban_list/meta.json`
- `mtg_modern_data/ban_list/history/YYYY-MM-DD.json`

## Pipeline Rule

The current meta period starts at the last `effective_date` in
`mtg_modern_data/ban_list/meta.json`. Scrapers and evaluation scripts must not
mix decklists across banlist periods.

When B&R changes:

1. Update the banlist timeline/snapshots.
2. Rebuild `mtg_modern_data/ban_list/current.json` and `meta.json`.
3. Re-run Top8 and Goldfish scrapers for the new period.
4. Re-run `evaluate_deck_strength.py`, `scripts/build_card_impact.py`, and `compose_meta.py`.

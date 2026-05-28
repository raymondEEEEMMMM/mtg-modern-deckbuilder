# MTG Modern Banlist History Design Spec

**Date**: 2026-05-27
**Author**: Claude Code

## 1. Overview

This spec defines how to obtain, store, and query historical Modern format banlist data for meta regression analysis. The system enables tracking how the meta game evolved after each ban/unban event.

## 2. Data Scope

- **Time Range**: 2021-01-01 to 2026-05-27 (5 years)
- **Format**: Modern only
- **Data Type**: Complete ban list snapshots per banlist change event

## 3. Storage Structure

```
ban_list/
├── current.json          # Current banlist (52 cards as of 2026-05-27)
├── meta.json             # Metadata and change history index
└── history/              # Historical snapshots
    └── YYYY-MM-DD.json   # One file per banlist change event
```

## 4. History File Schema

```json
{
  "effective_date": "2021-06-18",
  "format": "Modern",
  "description": "Modern Horizons 2 Ban List Update",
  "banned": ["Amped Raptor", "Ancient Den", ...],  // Full list at this date
  "restricted": [],
  "deck_banned": [],
  "source_url": "https://magic.wizards.com/en/content/standard-banned-and-restricted",
  "official_notes": "Brief reason for changes",
  "change_summary": {
    "added": ["card1", "card2"],
    "removed": []
  }
}
```

## 5. Data Acquisition

- **Source**: Wizards of the Coast official format page
- **Method**: curl/wget to fetch official historical records
- **Frequency**: Manual trigger for initial load, event-driven for future updates
- **Parsing**: Extract effective dates and card lists from official announcements

## 6. mtg_banlist Skill Updates

### New Features
| Feature | Description |
|---------|-------------|
| `--history` | List all available historical snapshots |
| `--date YYYY-MM-DD` | Show banlist as of specified date |
| `--diff DATE1 DATE2` | Compare two banlist snapshots |

### Behavior
- Without arguments: Shows current banlist
- With card name: Searches current banlist
- With `--history`: Lists all archived snapshots
- With `--date`: Shows state of banlist on that date
- With `--diff`: Shows what changed between dates

## 7. Implementation Tasks

1. Create `ban_list/history/` directory
2. Fetch Wizards official Modern banlist history page
3. Parse each banlist change event (effective date, cards)
4. Create one JSON file per event with full banlist
5. Update `mtg_banlist` skill to support `--history`, `--date`, `--diff` options
6. Update SPEC.md with history schema

## 8. Constraints

- Only Modern format (no other formats)
- Historical data is append-only (no modifications to archived files)
- Files named with effective date format: `YYYY-MM-DD.json`
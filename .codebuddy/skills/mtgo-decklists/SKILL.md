---
name: mtgo-decklists
description: MTGO official decklist ingestion skill. Use when the user asks to fetch, parse, validate, or integrate Magic Online Modern Challenge/Showcase/Preliminary decklists from mtgo.com. Covers Playwright-rendered pages, current ban-period filtering, decklist legality checks, quality reports, and integration with the Modern metagame pipeline as a decklist/performance supplement, not as a primary matchup source.
---

# MTGO Decklists Skill

## Overview

Fetch official Magic Online decklist pages from `mtgo.com/decklist/...` and parse
Modern event decklists, standings, and bracket text where available.

MTGO is a high-quality source for decklists and finishes. It is not expected to
provide full Swiss round pairings, so do not use it as the primary real matchup
matrix source.

## Quick Start

```bash
cd /Users/lianghaoming/mtg_agents_workplace

# Parse known current-period Modern URLs.
python3 scripts/scrape_mtgo_decklists.py --urls mtg_modern_data/sources/mtgo/modern_urls.txt

# Try browser-discovered URLs from the MTGO decklist page.
python3 scripts/scrape_mtgo_decklists.py --discover --max-events 10 --headless --no-html
```

Outputs:

```text
mtg_modern_data/sources/mtgo/raw/
mtg_modern_data/sources/mtgo/mtgo_decklists.json
mtg_modern_data/sources/mtgo/mtgo_quality_report.json
```

## Data Role

Use MTGO data for:

- Adding official Challenge/Showcase decklists.
- Performance scoring from placement, standings, and top cut where available.
- Cross-checking Top8/Goldfish archetype trends.

Do not use MTGO data for:

- Full round-level matchup matrix, unless a future page/API exposes complete
  pairings in a reliable structured form.

## Period Rule

Only integrate events with event date `>=` the current period start from:

```text
mtg_modern_data/ban_list/meta.json
```

Events before the current period may be saved as raw references, but must be
excluded from pipeline outputs.

## Parser Expectations

MTGO decklist pages are JavaScript-rendered. Use Playwright, not raw `urllib`.

Expected page sections:

- event title, e.g. `Modern Challenge 64`
- posted/event date
- player count
- optional bracket
- optional standings
- decklists with player, placement, maindeck, and sideboard

The parser should tolerate category labels such as `artifact`, `creature`,
`instant`, `land`, `basic_land`, `promo`, and similar MTGO display buckets.
Discovery must only accept URL slugs beginning with `modern-`; do not match
`premodern-` URLs just because they contain the substring `modern`.

## Integration Workflow

After successful MTGO scrape:

```bash
python3 evaluate_deck_strength.py --top 15
python3 scripts/build_card_impact.py
python3 compose_meta.py
```

The first version of the MTGO tool writes a standalone source output. Merge into
`evaluate_deck_strength.py` only after the quality report confirms stable parsing
and deduplication rules.

## Quality Checks

Before using MTGO data in the main pipeline, inspect:

- event count in current period
- decklist count
- count of 60-card maindecks and 15-card sideboards
- failed deck parses
- duplicate `(event_id, player)` rows
- legality against `mtg_modern_data/ban_list/current.json`

The PoC accepts legal 61-card maindecks. Track `maindeck_60_count` as a quality
metric, but do not reject otherwise legal decklists only because they exceed 60.

## Guardrails

- Do not scrape aggressively. MTGO pages are public but should be fetched slowly.
- Preserve raw rendered text/HTML snapshots for parser debugging.
- Use `--no-html` for normal refreshes; raw HTML snapshots are large and ignored
  by git.
- Keep source attribution: data comes from Magic: The Gathering Online / mtgo.com.
- If MTGO publishes only Top 8 for some events, record that limitation in the
  quality report instead of inflating sample confidence.

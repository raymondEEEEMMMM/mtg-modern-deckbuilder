---
name: goldfish-scraper
description: Use when scraping, debugging, or validating MTGGoldfish Modern decklists, tournament index, placements, or key-card data. Triggers include "scrape Goldfish", "MTGGoldfish fetch failed", "refresh tournament index", "Goldfish overlap with Top8", or whenever the agent needs to refresh the MTGGoldfish portion of the local metagame dataset.
---

# MTGGoldfish Scraper Skill

Scrape complete 75-card Modern decklists from MTGGoldfish in two phases:
tournament index first, then incremental decklist expansion. Decks already
present in MTGTop8 output can be filtered with `--skip-top8-overlap` to avoid
double-counting.

## Quick Start

```bash
# Resume from where the previous run stopped (default for refreshes)
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap

# First-time full scrape
python3 scrape_goldfish_two_phase.py

# Smoke test
python3 scrape_goldfish_two_phase.py --max-tournaments 3
```

## CLI Flags

| Flag | Default | Purpose |
|---|---|---|
| `--resume` | off | Phase 1 reuses `goldfish_tournament_index.json`; phase 2 skips tournaments already marked complete. Use on every refresh after the first run. |
| `--max-tournaments N` | all | Cap tournaments processed in phase 2. |
| `--skip-top8-overlap` | off | Drop decks whose card signature matches an entry in `*_top8_decklists.json`. Run after Top8. |

There is no `--help`. The script uses positional `sys.argv` parsing.

## Two-Phase Flow

```text
Phase 1: scrape tournament list page
   → goldfish_tournament_index.json (status per tournament)

Phase 2: iterate tournament index
   → for each non-complete tournament, expand all decklist pages
   → parse 60 + 15
   → legality check vs ban_list/current.json
   → mark tournament complete in the index
   → YYYY-MM-DD_goldfish_decklists.json
```

The `--resume` flag is what makes refreshes cheap: rerunning phase 2
processes only tournaments that were not yet complete in the on-disk index.

## Outputs

- `mtg_modern_data/decks/raw/decklists/goldfish_tournament_index.json` —
  phase-1 output, also the resume ledger for phase 2.
- `mtg_modern_data/decks/raw/decklists/YYYY-MM-DD_goldfish_decklists.json` —
  one file per scrape run, full 75-card lists.

## Cloudflare / Playwright

- Requires `playwright` and Chromium:
  `pip install playwright && python -m playwright install chromium`
- Goldfish is gated by Cloudflare. **Run non-headless** (do not pass
  `--headless`); headless mode is rejected by the challenge page.
- The scraper injects a user-agent and retry wrapper
  (`navigate_with_retry`, `scrape_goldfish_two_phase.py:176`) so transient
  4xx/5xx pages do not abort the run.

## Pipeline Position

```bash
python3 scrape_decklists_top8.py --max-events 999     # 1. Top8 first
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap  # 2. this
python3 evaluate_deck_strength.py --top 15             # 3. Fuse + strength
python3 scripts/build_card_impact.py                   # 4. Card impact
python3 compose_meta.py                                # 5. Meta + matchup
```

Always run Top8 first so `--skip-top8-overlap` has a fingerprint file to
match against.

## Common Issues

- **Cloudflare challenge never resolves**: headless mode or stale cookies.
  Run interactively (non-headless) once to refresh the session.
- **Index file never advances**: phase 1 is failing silently. Check the
  selector in the `tournaments = page.evaluate(...)` block near
  `scrape_goldfish_two_phase.py:413`; the page DOM shifts occasionally.
- **All decks marked illegal**: `ban_list/current.json` is stale. Refresh
  with the `mtg-banlist` skill.
- **Duplicates in fused output**: `--skip-top8-overlap` was not passed, or
  the Top8 decklist file was missing during the Goldfish run.

## Cross-References

- **REQUIRED BACKGROUND:** Use `mtg-banlist` to verify the current period
  before scraping, and to confirm legality of any flagged deck.
- **Run before:** `top8-scraper` (so the overlap filter has a fingerprint
  file).

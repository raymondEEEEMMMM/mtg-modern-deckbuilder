# Next Data Source Plan

## Context

Melee.gg integration has been removed from this project. The discarded prototype
had three practical problems:

- Network and login flow were unreliable and often required VPN intervention.
- Deck names were manually entered and too noisy to use as canonical archetype labels.
- Round/decklist coverage was too low to produce real matchup cells in the final matrix.

The current project remains usable for metagame and archetype strength analysis
through MTGTop8 and MTGGoldfish decklists. The matchup matrix in `meta/current.json`
is now explicitly heuristic.

## Current Reliable Core

- `scrape_decklists_top8.py`: full 75-card MTGTop8 decklists.
- `scrape_goldfish_two_phase.py`: MTGGoldfish full 75-card decklists.
- `scrape_decks_goldfish.py`: MTGGoldfish aggregate metagame share, key cards,
  and placement data.
- `evaluate_deck_strength.py`: merges legal Top8 + Goldfish decklists and builds
  `fused_archetypes.json`.
- `compose_meta.py`: builds meta structure and heuristic matchup matrix.

## Candidate Sources

### 1. TopDeck.gg API

Primary candidate for round-level structured data.

Validation goals:

- Can fetch Modern tournaments for the current ban period.
- Can filter completed events by date and format.
- Can retrieve standings, rounds, player IDs, and decklists in one or more calls.
- Decklists include structured card entries, not just free-form names.
- Round match records can be linked to player decklists.

Acceptance threshold for first integration:

- At least 5 completed Modern events in the current period.
- At least 100 match records with both players classifiable to canonical archetypes.
- At least 70% of matched players have usable decklist data.
- No login/browser automation required for normal refresh.

### 2. MTGO Official Decklists

Validated supplement for high-quality decklists and event finishes.

Use for:

- Decklist sample expansion.
- Challenge / Preliminary / League weighting.
- Top cut or standing-based performance scoring.

Known limitation:

- Swiss round pairings are not reliably available, so this is not expected to be
  the primary matchup source.

### 3. MTGDecks.net

Potential aggregate and cross-check source.

Use for:

- External metagame share sanity checks.
- Additional decklists if access and licensing are acceptable.
- Event discovery.

### 4. Magic: The Metagame

Potential external validation source for MTGO-derived metagame/matchup summaries.

Use for:

- Sanity-checking top archetypes.
- Comparing broad matchup trends if raw methodology is inspectable.

## Proposed Architecture

```text
Top8 + Goldfish decklists
  -> archetype profiles / card fingerprints
  -> fused_archetypes.json

Candidate round-level source
  -> raw tournaments + standings + rounds + decklists
  -> decklist card-based classifier
  -> player_id -> canonical_archetype
  -> real_matchup_matrix.json
```

Do not use source-provided deck names as the primary classifier. Use them only as
low-weight hints. The primary classifier should compare card composition against
the existing Top8 + Goldfish archetype profiles.

## Next Steps

1. Create a `sources/topdeck/` PoC script that fetches current-period Modern
   tournaments from TopDeck.gg. **Done:** `scripts/topdeck_poc.py`.
2. Save raw responses under `mtg_modern_data/sources/topdeck/raw/`. **Scaffolded.**
3. Generate a quality report with event count, round count, decklist coverage,
   and player-to-decklist join rate. **Scaffolded.**
4. Build a decklist-based archetype classifier using existing fused archetype
   key cards and card-frequency profiles. **Initial key-card classifier scaffolded.**
5. Produce a trial `real_matchup_matrix.json` only if the acceptance threshold is met.
6. Update `compose_meta.py` to consume the new matrix behind a source/quality gate.
7. Add MTGO official decklist ingestion as a parallel sample-expansion task. **Done:** `scripts/scrape_mtgo_decklists.py`.

## TopDeck PoC Usage

Dry-run payload generation:

```bash
python3 scripts/topdeck_poc.py --dry-run
```

Live API run:

```bash
TOPDECK_API_KEY=... python3 scripts/topdeck_poc.py
```

Expected outputs:

- `mtg_modern_data/sources/topdeck/topdeck_request_payload.json`
- `mtg_modern_data/sources/topdeck/raw/topdeck_modern_<period>.json`
- `mtg_modern_data/sources/topdeck/topdeck_quality_report.json`
- `mtg_modern_data/sources/topdeck/real_matchup_matrix_trial.json` only if quality gate passes

## TopDeck PoC Result: 2026-05-29

Network/API access works with `TOPDECK_API_KEY`; no browser automation is needed.

Current-period query (`2026-05-18` to `2026-05-29`):

- 1 Modern event
- 8 players
- 0 public decklists
- 0 classified matches

Wider 30-day query:

- 8 Modern events
- 98 players
- 29 players with public decklists
- 29.59% decklist/classification coverage
- 70 classified match records
- 46 archetype pairs
- top pair sample count: 5
- quality gate: failed

Main blocker: round data is available, but most TopDeck events do not expose
decklists. The usable data currently comes mostly from one 30-player event
(`impact-iq1-liga-gallega-modern`). TopDeck remains a viable supplemental source,
but it should not replace the heuristic matchup matrix until decklist coverage
improves or another source can provide player-to-decklist joins.

## MTGO PoC Usage

Discover and scrape recent official Modern decklist pages:

```bash
python3 scripts/scrape_mtgo_decklists.py --discover --max-events 3 --headless --no-html
```

Expected outputs:

- `mtg_modern_data/sources/mtgo/modern_urls.txt`
- `mtg_modern_data/sources/mtgo/raw/`
- `mtg_modern_data/sources/mtgo/mtgo_decklists.json`
- `mtg_modern_data/sources/mtgo/mtgo_quality_report.json`

## MTGO PoC Result: 2026-05-29

Browser rendering works with Playwright. URL discovery now filters by decklist
slug prefix `modern-`, so `premodern-` pages are excluded.
Use `--no-html` for routine refreshes; raw text is enough for parser auditing,
and raw HTML snapshots are treated as local debug artifacts.

Discovery sample:

- `modern-league-2026-05-2910628`
- `modern-challenge-64-2026-05-2812843376`
- `modern-league-2026-05-2810628`

Quality report:

- 3 current-period Modern events
- 82 parsed decklists
- 82 legal decklists
- 79 exact 60-card maindecks
- 82 exact 15-card sideboards
- 0 duplicate rows
- 0 failed deck blocks

Three legal decklists have 61-card maindecks. Keep them; use exact 60-card count
as a parser quality metric rather than a rejection rule.

MTGO is now the best next integration target for decklist sample expansion and
finish-weighted performance scoring. It still should not be treated as the
primary matchup source because Swiss pairings are not exposed reliably.

## Immediate Next Plan

1. Add an MTGO import step to `evaluate_deck_strength.py` behind a source flag.
2. Reuse the existing Top8/Goldfish decklist-card classifier to assign canonical
   archetypes from MTGO card composition, with player/page deck names as hints only.
3. Weight MTGO Challenge placements more heavily than League 5-0 lists; keep
   League data as metagame sample expansion, not direct win-rate evidence.
4. Rebuild `fused_archetypes.json`, then run `scripts/build_card_impact.py`.
5. Keep TopDeck as a watched matchup candidate, but do not feed its matchup
   matrix into `compose_meta.py` until decklist coverage reaches the quality gate.

## Quality Gate

A real matchup matrix should not be integrated unless the generated report shows:

- `source` is structured and reproducible without browser automation.
- `classified_match_count >= 100`.
- `classification_coverage >= 0.70`.
- `top_pair_sample_count >= 3` for at least several top archetype pairs.
- Output records include source event IDs, dates, sample sizes, and confidence.

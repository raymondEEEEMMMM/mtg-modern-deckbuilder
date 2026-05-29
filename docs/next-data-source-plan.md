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

Good supplement for high-quality decklists and event finishes.

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
   tournaments from TopDeck.gg.
2. Save raw responses under `mtg_modern_data/sources/topdeck/raw/`.
3. Generate a quality report with event count, round count, decklist coverage,
   and player-to-decklist join rate.
4. Build a decklist-based archetype classifier using existing fused archetype
   key cards and card-frequency profiles.
5. Produce a trial `real_matchup_matrix.json` only if the acceptance threshold is met.
6. Update `compose_meta.py` to consume the new matrix behind a source/quality gate.
7. Add MTGO official decklist ingestion as a parallel sample-expansion task.

## Quality Gate

A real matchup matrix should not be integrated unless the generated report shows:

- `source` is structured and reproducible without browser automation.
- `classified_match_count >= 100`.
- `classification_coverage >= 0.70`.
- `top_pair_sample_count >= 3` for at least several top archetype pairs.
- Output records include source event IDs, dates, sample sizes, and confidence.

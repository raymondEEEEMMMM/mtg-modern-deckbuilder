---
name: card-impact
description: Use when evaluating single-card influence on the Modern metagame, identifying archetype core cards, or assessing the impact of a ban or unban. Triggers include "how important is this card?", "core cards of [archetype]", "what does banning X affect?", "rebuild card impact", "card_impact.json is stale", or any question about a single card's role in the current Modern format.
---

# Modern Card Impact Skill

Build and query per-card influence metrics for the current ban period, derived
from real Top8 + Goldfish decklists plus the fused archetype profile.

## Quick Start

```bash
# Rebuild the full card impact report (writes mtg_modern_data/cards/card_impact.json)
python3 scripts/build_card_impact.py

# Just print the top 25 cards with their scores
python3 scripts/build_card_impact.py --top 25
```

## CLI Flags

| Flag | Default | Purpose |
|---|---|---|
| `--top N` | `25` | Number of top cards printed at the end of the run. |

The script uses `argparse`; `--help` works.

## Inputs

- `mtg_modern_data/decks/raw/decklists/*_top8_decklists.json`
- `mtg_modern_data/decks/raw/decklists/*_goldfish_decklists.json`
- `mtg_modern_data/decks/processed/fused_archetypes.json`
- `mtg_modern_data/cards/card_impact_config.json`

## Output

`mtg_modern_data/cards/card_impact.json` — schema:

```jsonc
{
  "cards": [
    {
      "name": "...",
      "format_impact_score": 0.0,   // environment-wide influence (higher = more central)
      "deck_count": 0,              // number of decklists containing the card
      "meta_share": 0.0,            // deck_count / total_decks
      "avg_copies": 0.0,
      "ubiquity": 0.0,              // share of archetypes that include the card
      "top_archetypes": ["..."]     // archetypes with highest core_score for this card
    }
  ],
  "archetype_profiles": {
    "ARCHETYPE": {
      "top_cards": [
        { "name": "...", "core_score": 0.0, "copies_avg": 0.0 }
      ]
    }
  }
}
```

- `format_impact_score` — for environment-wide questions
  ("how important is this card overall?").
- `archetype_profiles[ARCH].top_cards[].core_score` — for archetype-level
  questions ("is X a core card of Burn?").

## Reuse It From Code or Conversation

Read the JSON directly:

```python
import json
data = json.load(open("mtg_modern_data/cards/card_impact.json"))
for c in data["cards"][:10]:
    print(f"{c['name']:30s}  impact={c['format_impact_score']:.3f}  meta={c['meta_share']:.1%}")
```

For "core cards of <archetype>":

```python
prof = data["archetype_profiles"]["Burn"]
print([c["name"] for c in prof["top_cards"][:10]])
```

## Policy Reminders

- Re-run this script after any change to the input decklist set or after a
  B&R update, otherwise `format_impact_score` is stale.
- **Do not** claim causal win-rate impact from these metrics. They are
  usage and centrality, not win rate. Pair with `meta/current.json` (or a
  real matchup source) before saying "card X wins more games".
- Card names in the output are normalized; if a name does not match
  Scryfall, look it up via the Scryfall skill / API before publishing.

## Pipeline Position

```bash
python3 scrape_decklists_top8.py --max-events 999     # 1. Top8
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap  # 2. Goldfish
python3 evaluate_deck_strength.py --top 15             # 3. Fuse archetypes (this skill's input)
python3 scripts/build_card_impact.py                   # 4. this skill
python3 compose_meta.py                                # 5. Meta + matchup
```

The script depends on `fused_archetypes.json`, so it must run after
`evaluate_deck_strength.py`.

## Common Issues

- **Empty `cards` array**: no decklists in `decks/raw/decklists/`, or the
  file glob is wrong. Confirm files exist and re-run Top8 + Goldfish.
- **All `format_impact_score` near 0**: the deck count denominator
  collapsed (too few decks). Re-run the full pipeline with more events.
- **Missing archetype profile for an obvious deck**: name normalization
  mismatch. Check `mtg_modern_data/decks/archetype_name_map.json` or the
  `canonical_deck_name` function in `build_card_impact.py:64`.

## Cross-References

- **Upstream:** `top8-scraper` and `goldfish-scraper` produce the input
  decklists; `evaluate_deck_strength.py` produces the fused archetypes
  this script consumes.
- **REQUIRED BACKGROUND:** Use `mtg-banlist` to confirm the period before
  citing any score, since the output is period-bound.

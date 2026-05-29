---
name: card-impact
description: MTG Modern card impact analysis skill. Use when the user asks to evaluate single-card influence, identify format staples, analyze archetype core cards, estimate ban/unban impact, or explain why a card matters in the current Modern metagame. Runs the deterministic card impact pipeline from current-period Top8 and Goldfish decklists.
---

# Card Impact Skill

## Overview

Evaluate single-card influence in the current Modern period using legal Top8 and
Goldfish decklists. The calculation lives in `scripts/build_card_impact.py`; this
skill defines when to run it and how to interpret the output.

## Quick Start

```bash
cd /Users/lianghaoming/mtg_agents_workplace
python3 scripts/build_card_impact.py
```

Output:

```text
mtg_modern_data/cards/card_impact.json
```

## Inputs

- `mtg_modern_data/decks/raw/decklists/*_top8_decklists.json`
- `mtg_modern_data/decks/raw/decklists/*_goldfish_decklists.json`
- `mtg_modern_data/decks/processed/fused_archetypes.json`
- `mtg_modern_data/cards/card_impact_config.json`

Run `evaluate_deck_strength.py` first if `fused_archetypes.json` is stale.

## Metrics

### Format impact

Use `cards[].format_impact_score` to answer: "How much does this card affect the
overall Modern environment?"

Components:

- `meta_presence`: share of legal decklists using the card
- `top_tier_presence`: share of Tier 1-2 decklists using the card
- `archetype_count`: how many canonical archetypes use the card
- `avg_copies_when_played`: average weighted copies in decks that use it
- `specificity`: how concentrated the card is in its main archetype

Labels:

- `format_staple`: broad and high-impact card
- `major_role_player`: important card, often tied to top archetypes
- `archetype_card`: meaningful but narrower card
- `low_impact`: low current-period signal

### Archetype core score

Use `archetype_profiles[ARCHETYPE].top_cards[].core_score` to answer: "Is this
card core to this archetype?"

Components:

- `ubiquity`: share of that archetype's decks using the card
- `avg_copies`: average weighted copies across that archetype
- `copy_stability`: how stable the copy count is
- `specificity`: how much of the card's total usage belongs to that archetype

Labels:

- `archetype_core`: essential or near-essential card
- `strong_role_player`: important role player
- `flex_card`: common but not mandatory
- `low_signal`: weak archetype signal

## Ban/Unban Analysis Workflow

1. Run `python3 scripts/build_card_impact.py`.
2. Open `mtg_modern_data/cards/card_impact.json`.
3. Find the card in `cards`.
4. Inspect `top_archetypes` to identify affected archetypes.
5. For each affected archetype, inspect `archetype_profiles[ARCHETYPE].top_cards`
   and compare `core_score`, `ubiquity`, and `avg_copies`.
6. Classify impact:
   - High: high format impact plus high core score in Tier 1-2 archetypes.
   - Medium: narrow but high archetype core score, or broad but low copy count.
   - Low: low current-period usage or mostly sideboard/flex usage.

## Guardrails

- Do not treat `format_impact_score` as win-rate impact. It measures observed
  deck construction influence, not causal match win percentage.
- Sideboard cards are down-weighted by `sideboard_weight` in the config.
- Current output depends on current-period decklists only. Re-run scrapers after
  a B&R update before making ban/unban conclusions.
- For card-specific claims, cite exact fields from `card_impact.json`: score,
  deck count, presence, top archetypes, and archetype core score.

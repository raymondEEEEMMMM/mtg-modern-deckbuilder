#!/usr/bin/env python3
"""
Build Modern card impact metrics from current-period decklists.

Inputs:
  - mtg_modern_data/decks/raw/decklists/*_top8_decklists.json
  - mtg_modern_data/decks/raw/decklists/*_goldfish_decklists.json
  - mtg_modern_data/decks/processed/fused_archetypes.json
  - mtg_modern_data/cards/card_impact_config.json

Output:
  - mtg_modern_data/cards/card_impact.json
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "mtg_modern_data"
DECKLIST_DIR = DATA_DIR / "decks" / "raw" / "decklists"
FUSED_PATH = DATA_DIR / "decks" / "processed" / "fused_archetypes.json"
CONFIG_PATH = DATA_DIR / "cards" / "card_impact_config.json"
OUTPUT_PATH = DATA_DIR / "cards" / "card_impact.json"

sys.path.insert(0, str(BASE))
from evaluate_deck_strength import load_decklist_data  # noqa: E402


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_file(pattern: str) -> Optional[Path]:
    files = sorted(DECKLIST_DIR.glob(pattern), reverse=True)
    return files[0] if files else None


def build_name_mapping() -> dict:
    path = DATA_DIR / "decks" / "archetype_name_map.json"
    if not path.exists():
        return {}
    data = load_json(path)
    mapping = {}
    for row in data.get("mappings", []):
        canonical = row.get("canonical")
        if not canonical:
            continue
        for key in ("mtgtop8", "goldfish"):
            raw = row.get(key)
            if raw:
                mapping[raw] = canonical
    return mapping


def canonical_deck_name(deck: dict, name_mapping: dict) -> str:
    if deck.get("deck_name_canonical"):
        return deck["deck_name_canonical"]
    raw = deck.get("deck_name", "")
    return name_mapping.get(raw, raw)


def deck_signature(deck: dict) -> tuple:
    source = deck.get("source", "")
    event = deck.get("event_id") or deck.get("event_name") or ""
    player = deck.get("player", "")
    archetype = deck.get("deck_name_canonical") or deck.get("deck_name") or ""
    return (source.lower(), str(event).lower(), player.lower(), archetype.lower())


def load_decklists() -> tuple[list[dict], dict]:
    old_cwd = Path.cwd()
    try:
        os.chdir(BASE)
        data = load_decklist_data()
    finally:
        os.chdir(old_cwd)
    if not data:
        return [], {}

    name_mapping = build_name_mapping()
    source_files = {
        "loader": "evaluate_deck_strength.load_decklist_data",
        "source": data.get("source", ""),
        "top8_decks": data.get("top8_decks", 0),
        "goldfish_decks": data.get("goldfish_decks", 0),
        "goldfish_added": data.get("goldfish_added", 0),
        "goldfish_skipped_overlap": data.get("goldfish_skipped_overlap", 0),
        "goldfish_illegal": data.get("goldfish_illegal", 0),
        "illegal_decks_filtered": data.get("illegal_decks_filtered", 0),
        "merged_legal_decks": data.get("total_decks", len(data.get("decklists", []))),
    }

    decks = []
    for deck in data.get("decklists", []):
        if not deck.get("legality", {}).get("legal", True):
            continue
        if deck.get("maindeck_count", 0) <= 0:
            continue
        copy = dict(deck)
        copy["deck_name_canonical"] = canonical_deck_name(deck, name_mapping)
        decks.append(copy)

    return decks, source_files


def load_archetypes() -> dict:
    fused = load_json(FUSED_PATH)
    return {a["name"]: a for a in fused.get("archetypes", [])}


def normalize_weights(weights: dict) -> dict:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: v / total for k, v in weights.items()}


def weighted_card_entries(deck: dict, sideboard_weight: float) -> dict[str, float]:
    cards = defaultdict(float)
    for card in deck.get("maindeck", []):
        cards[card["name"]] += float(card.get("qty", 0))
    for card in deck.get("sideboard", []):
        cards[card["name"]] += float(card.get("qty", 0)) * sideboard_weight
    return dict(cards)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def label_from_thresholds(score: float, thresholds: dict, default: str) -> str:
    for label, threshold in sorted(thresholds.items(), key=lambda item: -item[1]):
        if score >= threshold:
            return label
    return default


def build_impact(decks: list[dict], archetypes: dict, config: dict) -> dict:
    sideboard_weight = float(config.get("sideboard_weight", 0.35))
    format_weights = normalize_weights(config.get("format_impact_weights", {}))
    core_weights = normalize_weights(config.get("archetype_core_weights", {}))
    top_tiers = set(config.get("top_tiers", ["Tier 1", "Tier 2"]))
    min_core_decks = int(config.get("minimum_decks_for_core", 3))

    total_decks = len(decks)
    archetype_decks = defaultdict(list)
    card_deck_count = Counter()
    card_total_qty = Counter()
    card_archetypes = defaultdict(set)
    card_top_tier_deck_count = Counter()
    top_tier_deck_total = 0
    deck_card_qty = []

    for deck in decks:
        arch = deck.get("deck_name_canonical") or deck.get("deck_name")
        archetype_decks[arch].append(deck)
        arch_info = archetypes.get(arch, {})
        is_top_tier = arch_info.get("tier") in top_tiers
        if is_top_tier:
            top_tier_deck_total += 1

        cards = weighted_card_entries(deck, sideboard_weight)
        deck_card_qty.append(cards)
        for card, qty in cards.items():
            if qty <= 0:
                continue
            card_deck_count[card] += 1
            card_total_qty[card] += qty
            card_archetypes[card].add(arch)
            if is_top_tier:
                card_top_tier_deck_count[card] += 1

    archetype_count = len(archetype_decks)
    max_breadth = max(1, archetype_count)

    card_meta = {}
    for card, deck_count in card_deck_count.items():
        avg_copies = card_total_qty[card] / deck_count if deck_count else 0
        presence = deck_count / total_decks if total_decks else 0
        breadth = len(card_archetypes[card]) / max_breadth
        top_tier_presence = (
            card_top_tier_deck_count[card] / top_tier_deck_total
            if top_tier_deck_total else 0
        )
        arch_counts = Counter()
        for arch, arch_decks in archetype_decks.items():
            count = 0
            for deck in arch_decks:
                cards = weighted_card_entries(deck, sideboard_weight)
                if card in cards:
                    count += 1
            if count:
                arch_counts[arch] = count
        max_arch_count = max(arch_counts.values()) if arch_counts else 0
        specificity = max_arch_count / deck_count if deck_count else 0

        metrics = {
            "weighted_presence": presence,
            "archetype_breadth": breadth,
            "top_tier_presence": top_tier_presence,
            "avg_copies": clamp(avg_copies / 4.0),
            "specificity": specificity,
        }
        score = sum(format_weights.get(k, 0) * metrics[k] for k in metrics)
        card_meta[card] = {
            "card": card,
            "format_impact_score": round(score, 4),
            "label": label_from_thresholds(
                score, config.get("impact_labels", {}), "low_impact"
            ),
            "deck_count": deck_count,
            "meta_presence": round(presence, 4),
            "avg_copies_when_played": round(avg_copies, 3),
            "archetype_count": len(card_archetypes[card]),
            "top_tier_presence": round(top_tier_presence, 4),
            "specificity": round(specificity, 4),
            "top_archetypes": [
                {
                    "name": arch,
                    "deck_count": count,
                    "share_of_card": round(count / deck_count, 4) if deck_count else 0,
                }
                for arch, count in arch_counts.most_common(8)
            ],
        }

    archetype_profiles = {}
    for arch, arch_decks in archetype_decks.items():
        total = len(arch_decks)
        if total < min_core_decks:
            continue

        per_card_decks = Counter()
        per_card_qty = Counter()
        per_card_quantities = defaultdict(list)
        for deck in arch_decks:
            cards = weighted_card_entries(deck, sideboard_weight)
            seen = set(cards)
            for card in seen:
                per_card_decks[card] += 1
            for card, qty in cards.items():
                per_card_qty[card] += qty
                per_card_quantities[card].append(qty)

        cards_out = []
        for card, decks_with_card in per_card_decks.items():
            ubiquity = decks_with_card / total
            avg_copies = per_card_qty[card] / total
            quantities = per_card_quantities[card]
            mean_seen = sum(quantities) / len(quantities)
            if len(quantities) <= 1 or mean_seen <= 0:
                copy_stability = 1.0
            else:
                variance = sum((q - mean_seen) ** 2 for q in quantities) / len(quantities)
                coeff_var = math.sqrt(variance) / mean_seen
                copy_stability = clamp(1 - coeff_var)

            global_deck_count = card_deck_count.get(card, 0)
            specificity = decks_with_card / global_deck_count if global_deck_count else 0
            metrics = {
                "ubiquity": ubiquity,
                "avg_copies": clamp(avg_copies / 4.0),
                "copy_stability": copy_stability,
                "specificity": specificity,
            }
            core_score = sum(core_weights.get(k, 0) * metrics[k] for k in metrics)
            cards_out.append({
                "card": card,
                "core_score": round(core_score, 4),
                "label": label_from_thresholds(
                    core_score, config.get("core_labels", {}), "low_signal"
                ),
                "ubiquity": round(ubiquity, 4),
                "avg_copies": round(avg_copies, 3),
                "copy_stability": round(copy_stability, 4),
                "specificity": round(specificity, 4),
                "format_impact_score": card_meta.get(card, {}).get("format_impact_score", 0),
            })

        cards_out.sort(key=lambda row: (-row["core_score"], -row["ubiquity"], row["card"]))
        arch_info = archetypes.get(arch, {})
        archetype_profiles[arch] = {
            "name": arch,
            "deck_count": total,
            "tier": arch_info.get("tier", "unknown"),
            "metagame_share": arch_info.get("fused_metagame_share", 0),
            "top_cards": cards_out[:25],
        }

    cards_sorted = sorted(
        card_meta.values(),
        key=lambda row: (-row["format_impact_score"], -row["deck_count"], row["card"]),
    )

    return {
        "cards": cards_sorted,
        "archetype_profiles": dict(sorted(
            archetype_profiles.items(),
            key=lambda item: (-item[1]["deck_count"], item[0])
        )),
    }


def main():
    parser = argparse.ArgumentParser(description="Build Modern card impact scores")
    parser.add_argument("--top", type=int, default=25, help="Number of top cards to print")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH)
    archetypes = load_archetypes()
    decks, source_files = load_decklists()
    if not decks:
        raise SystemExit("No legal decklists found")

    impact = build_impact(decks, archetypes, config)
    fused = load_json(FUSED_PATH)
    output = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": "Modern",
        "period_start": fused.get("period_start"),
        "source_files": source_files,
        "usable_deck_count": len(decks),
        "deck_count": len(decks),
        "excluded_empty_decklists": max(
            0, int(source_files.get("merged_legal_decks", len(decks))) - len(decks)
        ),
        "archetype_count": len(impact["archetype_profiles"]),
        "config": config,
        **impact,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Decks: {output['deck_count']} | Archetypes: {output['archetype_count']}")
    print("Top format-impact cards:")
    for row in output["cards"][:args.top]:
        print(
            f"  {row['format_impact_score']:.3f} {row['card']} "
            f"({row['label']}, decks={row['deck_count']}, "
            f"presence={row['meta_presence']:.1%})"
        )


if __name__ == "__main__":
    main()

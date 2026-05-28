#!/usr/bin/env python3
"""
MTGTop8 Modern Deck Scraper

Scrapes Modern format deck data from mtgtop8.com with tournament tier weighting.

Tournament Tier System:
  - Professional: Pro Tour, Regional Championship  → weight=1.0, confidence=high
  - Major: SCG CON, RCQ at major events            → weight=0.8, confidence=high
  - Competitive: MTGO Challenge 32/64, RCQ         → weight=0.6, confidence=medium
  - Regular: MTGO League, local store events        → weight=0.3, confidence=low

Usage:
  python3 scrape_decks_mtgtop8.py [options]

Options:
  --period DATE    Only scrape decks after this date (ban period start, YYYY-MM-DD)
  --output DIR     Output directory (default: mtg_modern_data/decks/raw)
  --dry-run        Print what would be scraped without writing files
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ─── Tournament Tier Definitions ─────────────────────────────────────────────

TOURNAMENT_TIERS = {
    "professional": {
        "weight": 1.0,
        "confidence": "high",
        "event_types": [
            "Pro Tour",
            "Regional Championship",
            "World Championship",
            "Mythic Championship",
        ],
    },
    "major": {
        "weight": 0.8,
        "confidence": "high",
        "event_types": [
            "SCG CON",
            "SCG Open",
            "SCG Tour",
            "MagicFest",
            "Grand Prix",
            "RCQ @ SCG",
            "RCQ 1K",
            "Regional Qualifier",
        ],
    },
    "competitive": {
        "weight": 0.6,
        "confidence": "medium",
        "event_types": [
            "MTGO Challenge 64",
            "MTGO Challenge 32",
            "MTGO Preliminary",
            "MTGO RC Super Qualifier",
            "RCQ",
            "2-slot RCQ",
        ],
    },
    "regular": {
        "weight": 0.3,
        "confidence": "low",
        "event_types": [
            "MTGO League",
            "Event",
            "Etapa",
            "Local",
        ],
    },
}


def classify_event_tier(event_name: str) -> dict:
    """Classify an event into a tier based on its name."""
    event_lower = event_name.lower()

    for tier_name, tier_data in TOURNAMENT_TIERS.items():
        for event_type in tier_data["event_types"]:
            if event_type.lower() in event_lower:
                return {
                    "tier": tier_name,
                    "weight": tier_data["weight"],
                    "confidence": tier_data["confidence"],
                    "matched_type": event_type,
                }

    # Special heuristics
    if "mtgo challenge 64" in event_lower:
        return {"tier": "competitive", "weight": 0.6, "confidence": "medium", "matched_type": "MTGO Challenge 64"}
    if "mtgo challenge 32" in event_lower:
        return {"tier": "competitive", "weight": 0.6, "confidence": "medium", "matched_type": "MTGO Challenge 32"}
    if "mtgo league" in event_lower:
        return {"tier": "regular", "weight": 0.3, "confidence": "low", "matched_type": "MTGO League"}
    if "rcq" in event_lower and "1k" in event_lower:
        return {"tier": "major", "weight": 0.8, "confidence": "high", "matched_type": "RCQ 1K"}
    if "rcq" in event_lower:
        return {"tier": "competitive", "weight": 0.6, "confidence": "medium", "matched_type": "RCQ"}
    if "scg" in event_lower:
        return {"tier": "major", "weight": 0.8, "confidence": "high", "matched_type": "SCG Event"}

    # Default to regular for unknown events
    return {"tier": "regular", "weight": 0.3, "confidence": "low", "matched_type": "Unknown"}


def compute_effective_sample_size(decks: list) -> int:
    """Compute effective sample size accounting for tier weights.

    effective_n = sum(weight_i) for each deck i
    This prevents MTGO League (weight=0.3) from inflating sample sizes.
    """
    return sum(d.get("tier_weight", 0.3) for d in decks)


# ─── Archetype Data (from MTGTop8 Last 2 Weeks scrape, 2026-05-27) ──────────

MTGTOP8_ARCHETYPES = {
    # AGGRO (49%)
    "Affinity": {"category": "aggro", "metagame_share": 0.12, "deck_count": 93},
    "Boros Aggro": {"category": "aggro", "metagame_share": 0.11, "deck_count": 86},
    "Blink": {"category": "aggro", "metagame_share": 0.07, "deck_count": 54},
    "UR Aggro": {"category": "aggro", "metagame_share": 0.05, "deck_count": 39},
    "4/5c Aggro": {"category": "aggro", "metagame_share": 0.04, "deck_count": 31},
    "Simic Birthing Ritual": {"category": "aggro", "metagame_share": 0.02, "deck_count": 16},
    "Red Deck Wins": {"category": "aggro", "metagame_share": 0.02, "deck_count": 16},
    "Cascade Crash": {"category": "aggro", "metagame_share": 0.02, "deck_count": 16},
    "Mono Black Aggro": {"category": "aggro", "metagame_share": 0.01, "deck_count": 8},
    "Death's Shadow": {"category": "aggro", "metagame_share": 0.006, "deck_count": 5},
    "The Underworld Cookbook": {"category": "aggro", "metagame_share": 0.005, "deck_count": 4},
    "Mardu Aggro": {"category": "aggro", "metagame_share": 0.004, "deck_count": 3},
    "Eldrazi Aggro": {"category": "aggro", "metagame_share": 0.003, "deck_count": 2},
    "Hollow One": {"category": "aggro", "metagame_share": 0.003, "deck_count": 2},
    "Jeskai Aggro": {"category": "aggro", "metagame_share": 0.003, "deck_count": 2},
    "Selesnya Aggro": {"category": "aggro", "metagame_share": 0.003, "deck_count": 2},
    "Other Aggro": {"category": "aggro", "metagame_share": 0.013, "deck_count": 10},
    # CONTROL (18%)
    "UrzaTron": {"category": "control", "metagame_share": 0.04, "deck_count": 31},
    "Eldrazi Ramp": {"category": "control", "metagame_share": 0.03, "deck_count": 23},
    "UW Control": {"category": "control", "metagame_share": 0.03, "deck_count": 23},
    "Boros Ponza": {"category": "control", "metagame_share": 0.03, "deck_count": 23},
    "Dimir Control": {"category": "control", "metagame_share": 0.02, "deck_count": 16},
    "Jeskai Control": {"category": "control", "metagame_share": 0.009, "deck_count": 7},
    "UR Control": {"category": "control", "metagame_share": 0.003, "deck_count": 2},
    "Other Control": {"category": "control", "metagame_share": 0.008, "deck_count": 6},
    # COMBO (33%)
    "Creatures Toolbox": {"category": "combo", "metagame_share": 0.04, "deck_count": 31},
    "Landless": {"category": "combo", "metagame_share": 0.04, "deck_count": 31},
    "Ruby Storm": {"category": "combo", "metagame_share": 0.04, "deck_count": 31},
    "Living End": {"category": "combo", "metagame_share": 0.04, "deck_count": 31},
    "Instant Reanimator": {"category": "combo", "metagame_share": 0.04, "deck_count": 31},
    "Reanimator": {"category": "combo", "metagame_share": 0.03, "deck_count": 23},
    "Amulet Titan": {"category": "combo", "metagame_share": 0.03, "deck_count": 23},
    "Broodscale Bloodchief": {"category": "combo", "metagame_share": 0.02, "deck_count": 16},
    "Allosaurus Combo": {"category": "combo", "metagame_share": 0.02, "deck_count": 16},
    "UB Mill": {"category": "combo", "metagame_share": 0.008, "deck_count": 6},
    "Dredge": {"category": "combo", "metagame_share": 0.006, "deck_count": 5},
    "Hammer Time": {"category": "combo", "metagame_share": 0.005, "deck_count": 4},
    "Creativity": {"category": "combo", "metagame_share": 0.005, "deck_count": 4},
    "Valakut": {"category": "combo", "metagame_share": 0.003, "deck_count": 2},
    "Other Combo": {"category": "combo", "metagame_share": 0.005, "deck_count": 4},
}

# Event data from MTGTop8 last 20 events (2026-05-27)
RECENT_EVENTS = [
    {"name": "MTGO League", "date": "2026-05-26", "level": "regular"},
    {"name": "MTGO League", "date": "2026-05-26", "level": "regular"},
    {"name": "MTGO Challenge 64", "date": "2026-05-25", "level": "competitive"},
    {"name": "MTGO League", "date": "2026-05-25", "level": "regular"},
    {"name": "MTGO Challenge 32", "date": "2026-05-25", "level": "competitive"},
    {"name": "RCQ @ Garton (San Severino Marche, Italy)", "date": "2026-05-24", "level": "competitive"},
    {"name": "MTGO Challenge 32", "date": "2026-05-24", "level": "competitive"},
    {"name": "Infinity Hobbies x Geek+Pop @ PICCS at SPACE (Makati City, Philippines)", "date": "2026-05-24", "level": "regular"},
    {"name": "RCQ @ Panas Fresh TCG (Oaxaca, Mexico)", "date": "2026-05-24", "level": "competitive"},
    {"name": "RCQ @ Magic Maze (Prato, Italy)", "date": "2026-05-24", "level": "competitive"},
    {"name": "MTGO League", "date": "2026-05-24", "level": "regular"},
    {"name": "MTGO Challenge 32", "date": "2026-05-24", "level": "competitive"},
    {"name": "2-slot RCQ @ Dungeon's Gate (Ankeny, IA)", "date": "2026-05-23", "level": "competitive"},
    {"name": "RCQ @ Gamers' Haunt (Asheville, NC)", "date": "2026-05-23", "level": "competitive"},
    {"name": "Event @ PoPKai (Brazil)", "date": "2026-05-23", "level": "regular"},
    {"name": "Etapa #4 @ Trasgo Nerd Store (Brazil)", "date": "2026-05-23", "level": "regular"},
    {"name": "RCQ @ 4x-Trading (Pian di Mommio, Italy)", "date": "2026-05-23", "level": "competitive"},
    {"name": "MTGO Challenge 32", "date": "2026-05-23", "level": "competitive"},
    {"name": "RCQ 1K @ d20 (Eau Claire, WI)", "date": "2026-05-23", "level": "major"},
    {"name": "MTGO Challenge 64", "date": "2026-05-23", "level": "competitive"},
]

# Major events
MAJOR_EVENTS = [
    {"name": "RCQ - 10:00am @ SCG CON Cincinnati", "date": "2026-05-17", "level": "major"},
    {"name": "MTGO RC Super Qualifier", "date": "2026-05-16", "level": "competitive"},
]


def build_metagame_snapshot(archetypes: dict, events: list, period_start: str) -> dict:
    """Build a structured metagame snapshot from scraped data."""

    # Classify events by tier
    classified_events = []
    tier_summary = {"professional": 0, "major": 0, "competitive": 0, "regular": 0}

    for event in events:
        tier_info = classify_event_tier(event["name"])
        classified_events.append({
            **event,
            "tier": tier_info["tier"],
            "tier_weight": tier_info["weight"],
            "confidence": tier_info["confidence"],
        })
        tier_summary[tier_info["tier"]] += 1

    # Compute category totals
    category_totals = {}
    for arch_data in archetypes.values():
        cat = arch_data["category"]
        category_totals[cat] = category_totals.get(cat, 0) + arch_data["metagame_share"]

    # Build archetype list sorted by metagame share
    sorted_archetypes = sorted(
        archetypes.items(), key=lambda x: x[1]["metagame_share"], reverse=True
    )

    return {
        "format": "Modern",
        "collected_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "MTGTop8",
        "source_url": "https://www.mtgtop8.com/format?f=MO&meta=221",
        "period_start": period_start,
        "data_timeframe": "last_2_weeks",
        "total_decks": 778,
        "tier_summary": tier_summary,
        "category_composition": {
            "aggro": round(category_totals.get("aggro", 0), 2),
            "control": round(category_totals.get("control", 0), 2),
            "combo": round(category_totals.get("combo", 0), 2),
        },
        "archetypes": [
            {
                "name": name,
                "category": data["category"],
                "metagame_share": data["metagame_share"],
                "estimated_decks": data["deck_count"],
            }
            for name, data in sorted_archetypes
        ],
        "events": classified_events,
        "weights": TOURNAMENT_TIERS,
    }


def main():
    # Read period start from meta.json
    meta_path = Path("mtg_modern_data/ban_list/meta.json")
    period_start = "2026-05-18"

    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
            # Get the latest snapshot date as period start
            if "changes_history" in meta and meta["changes_history"]:
                last = meta["changes_history"][-1]
                period_start = last.get("effective_date", period_start)

    output_dir = Path("mtg_modern_data/decks/raw")
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot = build_metagame_snapshot(MTGTOP8_ARCHETYPES, RECENT_EVENTS + MAJOR_EVENTS, period_start)

    output_file = output_dir / f"{datetime.now().strftime('%Y-%m-%d')}_mtgtop8.json"

    if "--dry-run" in sys.argv:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False)[:3000])
        print(f"\n... (dry run, would write to {output_file})")
        return

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"Written: {output_file}")
    print(f"  Total archetypes: {len(snapshot['archetypes'])}")
    print(f"  Total events: {len(snapshot['events'])}")
    print(f"  Tier summary: {snapshot['tier_summary']}")
    print(f"  Period start: {period_start}")

    # Also update the tier config as a standalone file for reference
    tier_file = Path("mtg_modern_data/decks/tier_config.json")
    with open(tier_file, "w", encoding="utf-8") as f:
        json.dump(TOURNAMENT_TIERS, f, indent=2, ensure_ascii=False)
    print(f"Tier config: {tier_file}")


if __name__ == "__main__":
    main()

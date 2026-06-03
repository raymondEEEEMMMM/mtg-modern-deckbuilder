#!/usr/bin/env python3
"""
Modern Meta Composition Builder (Phase 4)

Reads Phase 3 output (fused_archetypes.json + top_decks.json) and constructs
the current environment Meta structure:

  1. Meta composition by archetype category (aggro/control/midrange/combo)
  2. Coverage rate — fraction of meta represented by top decks
  3. Key matchup landscape — category heuristic + strength adjustment
  4. Dominant archetypes and meta calls
  5. Banlist impact assessment for current period

Round-level matchup data is not currently integrated. The matrix is explicitly
heuristic until a reliable structured event source is added.

Output:
  meta/current.json — comprehensive Meta snapshot

Usage:
  python3 compose_meta.py
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "mtg_modern_data"

# ─── Paths ────────────────────────────────────────────────────────────────────
FUSED_PATH       = DATA_DIR / "decks" / "processed" / "fused_archetypes.json"
TOP_N_PATH       = DATA_DIR / "decks" / "top_n" / "top_decks.json"
META_PATH        = DATA_DIR / "meta" / "current.json"
BANLIST_PATH     = DATA_DIR / "ban_list" / "current.json"
BAN_META_PATH    = DATA_DIR / "ban_list" / "meta.json"

# ─── Category Interaction Matrix ──────────────────────────────────────────────
# General Modern format heuristics: [attacker_row, defender_col]
# Values: +2 = strong advantage, +1 = slight advantage, 0 = even,
#         -1 = slight disadvantage, -2 = strong disadvantage
# Order: aggro, control, midrange, combo
CATEGORY_INTERACTION = {
    "aggro":     {"aggro": 0,  "control": -1, "midrange":  1, "combo":  1},
    "control":   {"aggro":  1, "control":  0, "midrange": -1, "combo": -1},
    "midrange":  {"aggro": -1, "control":  1, "midrange":  0, "combo":  0},
    "combo":     {"aggro": -1, "control":  1, "midrange":  0, "combo":  0},
}


def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"[WARN] Missing: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_meta_composition(archetypes: list) -> dict:
    """Compute category distribution from archetype metagame shares."""
    cat_shares = defaultdict(float)
    cat_counts = defaultdict(int)
    total_share = 0.0

    for arch in archetypes:
        cat = arch.get("category", "other")
        share = arch.get("fused_metagame_share", 0)
        cat_shares[cat] += share
        cat_counts[cat] += 1
        total_share += share

    # Normalize to ensure shares sum to 1.0
    composition = {}
    for cat in ["aggro", "control", "midrange", "combo"]:
        composition[cat] = round(cat_shares.get(cat, 0) / total_share, 4) if total_share > 0 else 0

    return composition, cat_counts


def compute_coverage_rate(archetypes: list, top_n: int = 15) -> float:
    """Fraction of total metagame share covered by top N decks."""
    sorted_arches = sorted(archetypes, key=lambda a: a.get("fused_metagame_share", 0), reverse=True)
    top_share = sum(a.get("fused_metagame_share", 0) for a in sorted_arches[:top_n])
    total_share = sum(a.get("fused_metagame_share", 0) for a in archetypes)
    return round(top_share / total_share, 4) if total_share > 0 else 0


def build_matchup_landscape(top_decks: list, archetypes: list) -> dict:
    """
    Build a matchup interaction matrix for top decks using:
    1. Category-level heuristics as base
    2. Adjusted by strength_score differential

    Cells include source="heuristic" so downstream consumers do not mistake the
    matrix for observed match results.
    """
    # Build lookup
    arch_map = {a["name"]: a for a in archetypes}
    matchup_matrix = {}
    heuristic_used = 0

    for d1 in top_decks:
        name1 = d1["name"]
        cat1 = d1.get("category", "midrange")
        score1 = d1.get("strength_score", 0)
        matchup_row = {}

        for d2 in top_decks:
            name2 = d2["name"]
            if name1 == name2:
                matchup_row[name2] = {"advantage": 0, "confidence": "mirror"}
                continue

            cat2 = d2.get("category", "midrange")
            score2 = d2.get("strength_score", 0)

            # Base: category interaction
            base = CATEGORY_INTERACTION.get(cat1, {}).get(cat2, 0)

            # Strength differential adjustment (±0.5 per 20 score points)
            diff = (score1 - score2) / 40.0
            diff = max(-1.0, min(1.0, diff))

            advantage = round(base + diff, 2)
            advantage = max(-2.0, min(2.0, advantage))

            # Confidence describes heuristic stability, not observed match data.
            a1 = arch_map.get(name1, {})
            a2 = arch_map.get(name2, {})
            sample1 = a1.get("decklist_count", 0)
            sample2 = a2.get("decklist_count", 0)
            conf_score = min(sample1, sample2)
            if conf_score >= 30:
                confidence = "medium"
            else:
                confidence = "low"

            matchup_row[name2] = {
                "advantage": advantage,
                "confidence": confidence,
                "source": "heuristic",
            }
            heuristic_used += 1

        matchup_matrix[name1] = matchup_row

    if heuristic_used > 0:
        print(f"    Heuristic cells: {heuristic_used}")

    return matchup_matrix


def identify_meta_archetypes(archetypes: list) -> dict:
    """
    Classify archetypes by their role in the meta:
    - dominant: Tier 1, high share
    - established: Tier 2, significant presence
    - niche: Tier 3+, situational picks
    - meta_call: decks positioned to beat the dominant strategy
    """
    dominant = []
    established = []
    niche = []
    meta_calls = []

    # Find dominant category
    cat_shares = defaultdict(float)
    for a in archetypes:
        cat_shares[a.get("category", "other")] += a.get("fused_metagame_share", 0)
    dominant_cat = max(cat_shares, key=cat_shares.get) if cat_shares else "aggro"

    for a in archetypes:
        tier = a.get("tier", "Tier 4")
        share = a.get("fused_metagame_share", 0)
        cat = a.get("category", "other")

        if tier == "Tier 1":
            dominant.append(a["name"])
        elif tier == "Tier 2" and share >= 0.015:
            established.append(a["name"])
        elif tier == "Tier 2":
            established.append(a["name"])
        else:
            niche.append(a["name"])

        # Meta call: has category advantage against dominant + low own share
        if (tier in ("Tier 2", "Tier 3")
                and cat in CATEGORY_INTERACTION
                and CATEGORY_INTERACTION[cat].get(dominant_cat, 0) >= 1
                and share < 0.03):
            meta_calls.append(a["name"])

    return {
        "dominant": dominant,
        "established": established,
        "niche": niche[:20],  # cap for readability
        "meta_calls": meta_calls[:10],
        "dominant_category": dominant_cat,
    }


def assess_banlist_impact(banlist: dict, ban_meta: dict) -> dict:
    """Analyze the impact of the current banlist changes on the meta."""
    if not ban_meta:
        return {"status": "no_ban_data"}

    changes = ban_meta.get("changes_history", [])
    current_change = None
    for c in reversed(changes):
        if c.get("effective_date") == banlist.get("effective_date"):
            current_change = c
            break

    if not current_change:
        return {"status": "no_change_in_current_period"}

    added = current_change.get("changes", {}).get("added", [])
    removed = current_change.get("changes", {}).get("removed", [])

    impacted_decks = []
    # Map banned/unbanned cards to likely impacted archetypes
    card_impact = {
        "Lotus Field": {"impacts": ["Lotus Field Combo", "Amulet Titan"], "type": "banned"},
        "Phlage, Titan of Fire's Fury": {"impacts": ["Boros Energy", "Red Deck Wins"], "type": "banned"},
        "Violent Outburst": {"impacts": ["Crashing Footfalls", "Living End"], "type": "unbanned"},
        "Umezawa's Jitte": {"impacts": ["Various creature decks"], "type": "unbanned"},
    }

    for card in added:
        if card in card_impact:
            info = card_impact[card]
            impacted_decks.append({
                "card": card,
                "action": "banned",
                "likely_impacted": info["impacts"],
                "severity": "high" if info["type"] == "banned" else "medium"
            })
        else:
            impacted_decks.append({
                "card": card,
                "action": "banned",
                "likely_impacted": ["unknown"],
                "severity": "medium"
            })

    for card in removed:
        if card in card_impact:
            info = card_impact[card]
            impacted_decks.append({
                "card": card,
                "action": "unbanned",
                "likely_impacted": info["impacts"],
                "severity": "medium"
            })
        else:
            impacted_decks.append({
                "card": card,
                "action": "unbanned",
                "likely_impacted": ["unknown"],
                "severity": "low"
            })

    return {
        "period_changes": {
            "added_banned": added,
            "removed_banned": removed,
        },
        "impacted_decks": impacted_decks,
    }


def build_category_insights(archetypes: list, composition: dict) -> dict:
    """Generate per-category insights with key representatives."""
    cat_decks = defaultdict(list)
    for a in archetypes:
        cat = a.get("category", "other")
        cat_decks[cat].append(a)

    insights = {}
    for cat in ["aggro", "control", "midrange", "combo"]:
        decks = cat_decks.get(cat, [])
        decks_sorted = sorted(decks, key=lambda d: d.get("fused_metagame_share", 0), reverse=True)
        top3 = decks_sorted[:3]
        avg_consistency = 0
        avg_power = 0
        if decks:
            avg_consistency = round(sum(d.get("deck_consistency", 0) for d in decks) / len(decks), 3)
            avg_power = round(sum(d.get("card_power_density", 0) for d in decks) / len(decks), 3)

        insights[cat] = {
            "share": composition.get(cat, 0),
            "deck_count": len(decks),
            "top_representatives": [
                {
                    "name": d["name"],
                    "share": d.get("fused_metagame_share", 0),
                    "tier": d.get("tier", "Tier 4"),
                    "key_cards": d.get("key_cards", [])[:3]
                }
                for d in top3
            ],
            "avg_consistency": avg_consistency,
            "avg_power_density": avg_power,
        }

    return insights


def main():
    print("=" * 60)
    print("Phase 4: Composing Modern Meta Structure")
    print("=" * 60)

    # ─── Load data ────────────────────────────────────────────────────────
    fused = load_json(FUSED_PATH)
    top_n_data = load_json(TOP_N_PATH)
    banlist = load_json(BANLIST_PATH)
    ban_meta = load_json(BAN_META_PATH)

    if not fused or not fused.get("archetypes"):
        print("[ERROR] No fused_archetypes data. Run Phase 3 first.")
        return

    archetypes = fused["archetypes"]
    top_decks = top_n_data.get("decks", []) if top_n_data else []
    period_start = fused.get("period_start", "")
    period_end = fused.get("period_end", "")
    total_decklists = fused.get("decklist_sample_size", 0)
    total_archetypes = fused.get("total_archetypes", len(archetypes))
    tier_dist = fused.get("tier_distribution", {})

    print(f"  Archetypes: {total_archetypes}")
    print(f"  Decklists:  {total_decklists}")
    print(f"  Period:     {period_start} ~ {period_end}")

    # ─── 1. Meta composition ──────────────────────────────────────────────
    composition, cat_counts = build_meta_composition(archetypes)
    print(f"\n  Category Distribution:")
    for cat, share in composition.items():
        print(f"    {cat:10s}: {share:.1%} ({cat_counts.get(cat, 0)} archetypes)")

    # ─── 2. Coverage rate ─────────────────────────────────────────────────
    coverage_15 = compute_coverage_rate(archetypes, top_n=15)
    coverage_10 = compute_coverage_rate(archetypes, top_n=10)
    print(f"\n  Coverage (Top 10): {coverage_10:.1%}")
    print(f"  Coverage (Top 15): {coverage_15:.1%}")

    # ─── 3. Matchup landscape ─────────────────────────────────────────────
    print(f"\n  Building matchup matrix for Top {len(top_decks)} decks...")
    matchup_matrix = build_matchup_landscape(top_decks, archetypes)

    # ─── 4. Meta archetype identification ─────────────────────────────────
    meta_roles = identify_meta_archetypes(archetypes)
    print(f"  Dominant:  {meta_roles['dominant']}")
    print(f"  Meta calls: {meta_roles['meta_calls']}")

    # ─── 5. Category insights ────────────────────────────────────────────
    cat_insights = build_category_insights(archetypes, composition)

    # ─── 6. Banlist impact ────────────────────────────────────────────────
    ban_impact = assess_banlist_impact(banlist, ban_meta)

    # ─── Assemble output ──────────────────────────────────────────────────
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data_period_end = period_end or today

    output = {
        "generated_date": now,
        "based_on_ban_list_date": banlist.get("effective_date", period_start),
        "data_period": {
            "start": period_start,
            "end": data_period_end,
        },
        "total_decks_analyzed": total_decklists,
        "total_archetypes": total_archetypes,
        "tier_distribution": tier_dist,
        "top_decks": [
            {
                "rank": d.get("rank", 0),
                "name": d["name"],
                "category": d.get("category", ""),
                "tier": d.get("tier", ""),
                "strength_score": d.get("strength_score", 0),
                "metagame_share": d.get("fused_metagame_share", 0),
                "key_cards": d.get("key_cards", [])[:5],
            }
            for d in top_decks
        ],
        "meta_composition": composition,
        "coverage_rate": {
            "top_10": coverage_10,
            "top_15": coverage_15,
        },
        "category_insights": cat_insights,
        "meta_roles": meta_roles,
        "matchup_data_status": {
            "source": "heuristic",
            "real_round_level_source": None,
            "notes": "Melee integration removed; reliable structured sources are pending evaluation.",
        },
        "matchup_matrix": matchup_matrix,
        "banlist_impact": ban_impact,
    }

    # ─── Write output ─────────────────────────────────────────────────────
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  ✅ Written: {META_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()

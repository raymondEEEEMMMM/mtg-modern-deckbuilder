#!/usr/bin/env python3
"""
Modern Deck Strength Evaluator (Phase 3 - Decklist-Based)

Rebuilds the evaluation model using actual 75-card decklists instead of
aggregated archetype data. Key improvements:

  1. Real key_cards extracted from decklists (most-played non-land cards)
  2. Archetype mapping based on card overlap (not just name heuristics)
  3. Metagame share from actual decklist counts
  4. New dimensions: deck consistency, card concentration, build diversity
  5. Still fuses with Goldfish placement data for tournament performance

Strength Score Components:
  1. Metagame Share (35%) - from decklist count + Top8/Goldfish correction
  2. Performance Score (30%) - from Goldfish placement data, tier-weighted
  3. Deck Consistency (15%) - how tightly clustered are builds within an archetype
  4. Card Power Density (10%) - how many format-staple cards does the deck run
  5. Tournament Win Indicator (10%) - 1st place finishes in competitive+ events

Output:
  - decks/processed/fused_archetypes.json  — unified archetype list with fused scores
  - decks/top_n/top_decks.json             — ranked Top N decks with tier labels

Usage:
  python3 evaluate_deck_strength.py [--top N]
"""

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ─── Archetype Name Normalization ────────────────────────────────────────────
# Maps raw deck_name from MTGTop8 to canonical archetype names

ARCHETYPE_NORMALIZE = {
    # Case/format variants
    "UrzaTron": "UW Tron",
    "Urzatron": "UW Tron",
    "UW Control": "UW Control",
    "Uw Control": "UW Control",
    "Ub Mill": "UB Mill",

    # Name variants → canonical
    "Izzet Affinity": "Affinity",
    "Pinnacle Affinity": "Affinity",
    "Tommaso Ciampolini": "Affinity",  # Named by player, but Affinity build
    "Izzet Prowess": "UR Prowess",
    "UR Cutter Prowess": "UR Prowess",
    "Ur Cutter Prowess": "UR Prowess",
    "Russian Prowess": "UR Prowess",
    "Prowess": "UR Prowess",
    "Landless Belcher": "Landless",
    "Goblins Combo": "Landless",  # Belcher variant
    "Boros Aggro": "Boros Energy",  # Post-ban, same shell as Boros Energy (Ajani+Guide)
    "Jeskai Energy": "Boros Energy",  # Energy variant
    "Domain Rhinos": "Crashing Footfalls",
    "Temur Rhinos": "Crashing Footfalls",
    "Simic Birthing Ritual": "Birthing Ritual",
    "Selesnya Aggro Birthing Ritual": "Birthing Ritual",
    "Simic Ritual": "Birthing Ritual",
    "Mono Green Aggro": "Mono-G Aggro",
    "Mono": "Mono-Black Midrange",
    "Mono Black Aggro Necrodominance": "Mono-Black Midrange",
    "Azorius Blink": "Blink",
    "Orzhov Blink": "Blink",
    "Esper Blink": "Blink",
    "Mardu Blink": "Blink",
    "Domain Blink": "Blink",
    "Esper Eugè": "Blink",
    "Frog Legs": "Frog Combo",
    "Gabriele Del Tempora": "Dimir Control",  # Player name, Dimir build
    "Grixis Death Shadow": "Death's Shadow",
    "Samwise Combo": "Yawgmoth",  # Samwise + Yawgmoth combo
    "Burn": "Red Deck Wins",
    "Chord Toolbox": "Creatures Toolbox",
    "Scepter Chant": "UW Control",  # Scepter/Chant is UW Control variant
    "Hollow One": "Hollow One",
    "Soultrader": "Sacrifice Combo",
}

# Category mapping for canonical names
CATEGORY_MAP = {
    # ── Aggro ──
    "Affinity": "aggro",
    "Boros Energy": "aggro",
    "UR Prowess": "aggro",
    "4/5c Aggro": "aggro",
    "Birthing Ritual": "aggro",
    "Red Deck Wins": "aggro",
    "Cascade Crash": "aggro",
    "Death's Shadow": "aggro",
    "The Underworld Cookbook": "aggro",
    "Mardu Aggro": "aggro",
    "Mono-G Aggro": "aggro",
    "Hollow One": "aggro",
    "UR Aggro": "aggro",
    "Mono Black Aggro": "aggro",
    "Jeskai Aggro": "aggro",
    "Selesnya Aggro": "aggro",
    "Eldrazi Aggro": "aggro",
    "Merfolk": "aggro",
    "Other Aggro": "aggro",
    # Previously unknown — aggro
    "Boros": "aggro",
    "Dimir Aggro": "aggro",
    "Izzet Aggro": "aggro",
    "Izzet Metalcraft": "aggro",
    "Izzet Steel-Cutter": "aggro",
    "Gruul Aggro": "aggro",
    "Sultai Aggro": "aggro",
    "Temur Aggro": "aggro",
    "Simic Aggro": "aggro",
    "Mono-Blue Merfolk": "aggro",
    "Boros Merfolk": "aggro",
    "Mono-Red": "aggro",
    "R": "aggro",
    "UR": "aggro",
    "Mono-Red Eldrazi": "aggro",
    "Gruul Hardened Scales": "aggro",
    "Dimir Shadow": "aggro",
    "Rakdos Death's Shadow": "aggro",
    "Grixis Death's Shadow": "aggro",
    "Jund Hollow One": "aggro",
    "Izzet Phoenix": "aggro",
    "Izzet Wizards": "aggro",

    # ── Midrange ──
    "Blink": "midrange",
    # Previously unknown — midrange
    "Grixis Midrange": "midrange",
    "Esper Midrange": "midrange",
    "Orzhov Midrange": "midrange",
    "Rakdos Midrange": "midrange",
    "Jund Midrange": "midrange",
    "Simic Midrange": "midrange",
    "The Rock": "midrange",
    "Mono-White Midrange": "midrange",
    "Golgari Devotion": "midrange",
    "Necrodominance": "midrange",
    "4c Omnath": "midrange",
    "Mono-Green": "midrange",
    "Dimir": "midrange",
    "Grixis": "midrange",
    "Jund": "midrange",
    "BG": "midrange",
    "BRG": "midrange",
    "Simic": "midrange",
    "WUB": "midrange",
    "WUR": "midrange",
    "URG": "midrange",
    "WRG": "midrange",
    "UBRG": "midrange",
    "Sultai Affinity": "midrange",
    "Gruul Eldrazi Broodscale": "midrange",
    "Mono-Green Eldrazi Broodscale": "midrange",
    "Bant GenericBlink": "midrange",
    "Orzhov GenericBlink": "midrange",
    "Selesnya GenericBlink": "midrange",
    "Boros Miracles": "midrange",
    "Golgari Combo": "midrange",

    # ── Control ──
    "UW Tron": "control",
    "UW Control": "control",
    "Eldrazi Ramp": "control",
    "Eldrazi Tron": "control",
    "Boros Ponza": "control",
    "Dimir Control": "control",
    "Mono-Black Midrange": "control",
    "Dimir Midrange": "control",
    "Sultai Midrange": "control",
    "Jeskai Control": "control",
    "UR Control": "control",
    "Other Control": "control",
    # Previously unknown — control
    "Azorius Control": "control",
    "Azorius Control (Kaheera)": "control",
    "Esper Control": "control",
    "Grixis Control": "control",
    "Mono-White Control": "control",
    "Boros Control": "control",
    "Dimir Mill": "control",
    "Mono-Blue Tron": "control",
    "Colorless Eldrazi Tron": "control",
    "Mono-Green Tron": "control",
    "Mono-Green Eldrazi Tron": "control",
    "Gruul Eldrazi Tron": "control",
    "Colorless Eldrazi": "control",
    "Colorless": "control",
    "Mono-Blue Belcher": "control",
    "Lantern": "control",
    "Miracles": "control",
    "Gruul Eldrazi Ramp": "control",
    "W-U-B-R-G Omnath": "control",
    "W-U-B-G": "control",

    # ── Combo ──
    "Creatures Toolbox": "combo",
    "Landless": "combo",
    "Ruby Storm": "combo",
    "Living End": "combo",
    "Instant Reanimator": "combo",
    "Reanimator": "combo",
    "Amulet Titan": "combo",
    "Dredge": "combo",
    "Hammer Time": "combo",
    "Creativity": "combo",
    "Goryo's Vengeance": "combo",
    "Crashing Footfalls": "combo",
    "UB Mill": "combo",
    "Yawgmoth": "combo",
    "Frog Combo": "combo",
    "Sacrifice Combo": "combo",
    "Grixis Reanimator": "combo",
    "Allosaurus Combo": "combo",
    "Other Combo": "combo",
    "Valakut": "combo",
    "Broodscale Bloodchief": "combo",
    # Previously unknown — combo
    "Mono-Red Ruby Storm": "combo",
    "Mono-Red Storm": "combo",
    "Storm": "combo",
    "Mono-Red Combo": "combo",
    "Mono-Green Amulet Titan": "combo",
    "Simic Amulet Titan": "combo",
    "Boros Amulet Titan": "combo",
    "Boros Belcher": "combo",
    "Boros Combo": "combo",
    "Glimpse Combo": "combo",
    "Devoted Combo": "combo",
    "Sam Combo": "combo",
    "Gruul Combo": "combo",
    "Abzan Combo": "combo",
    "Asmo Food": "combo",
    "Gruul Broodscale": "combo",
    "Simic Neoform": "combo",
    "Naya Scapeshift": "combo",
    "Esper Reanimator": "combo",
    "Esper Goryo's": "combo",
    "Grixis Creativity": "combo",
    "Grixis Reanimator": "combo",
    "Golgari Yawgmoth": "combo",
    "Sultai Living End": "combo",
    "Bant Living End": "combo",
    "Temur Living End": "combo",
    "W-U-B-G Goryo's": "combo",
    "W-U-B-G Dredge": "combo",
    "U-B-R-G Dredge": "combo",
    "W-U-R-G Domain Zoo": "combo",
    "W-U-R-G Ritual": "combo",
    "W-U-B-G Combo": "combo",
    "W-U-B-G Samwise Gamgee Combo": "combo",
    "W-U-B-R-G Creativity": "combo",
    "W-U-B-R-G (Kaheera)": "combo",
    "W-U-R-G": "combo",
    "W-U-B-R-G": "combo",
    "W-U-B-G": "combo",
    "U-B-R-G": "combo",
    "Jeskai Wizards": "midrange",
    "W-U-B-G": "midrange",
    "Dimir Mill": "combo",
}


# ─── Format Staples ──────────────────────────────────────────────────────────
# Cards that define competitive Modern — presence indicates deck strength

FORMAT_STAPLES = {
    # Interactive staples
    "Lightning Bolt", "Ragavan, Nimble Pilferer", "Solitude", "Subtlety",
    "Endurance", "Force of Negation", "Thoughtseize", "Fatal Push",
    "Orcish Bowmasters", "Mishra's Bauble",

    # Value engines
    "Urza's Saga", "Ocelot Pride", "Guide of Souls",
    "Kappa Cannoneer", "Pinnacle Emissary",

    # Ramp/acceleration
    "Mox Opal", "Arid Mesa", "Flooded Strand", "Scalding Tarn",

    # Sideboard staples (format warping)
    "Consign to Memory", "Mystical Dispute", "Vexing Bauble",
    "Engineered Explosives", "Wrath of the Skies", "Tormod's Crypt",

    # New powerful cards
    "Ajani, Nacatl Pariah", "Phelia, Exuberant Shepherd",
    "Ketramose, the New Dawn", "Quantum Riddler",
    "Kozilek's Command", "Sink into Stupor",
}


# ─── Core Computation ────────────────────────────────────────────────────────

def normalize_archetype_name(name: str) -> str:
    """Map raw deck_name to canonical archetype."""
    return ARCHETYPE_NORMALIZE.get(name, name)


def extract_key_cards(decks: list, n: int = 5) -> list:
    """Extract top N non-land key cards from a list of deck dicts.

    Returns list of {name, total_qty, deck_count, ubiquity}.
    """
    card_counter = Counter()
    card_deck_count = Counter()

    # Common land names to exclude
    LANDS = {
        "Mountain", "Plains", "Island", "Swamp", "Forest",
        "Sacred Foundry", "Flooded Strand", "Marsh Flats", "Arid Mesa",
        "Windswept Heath", "Elegant Parlor", "Godless Shrine",
        "Hallowed Fountain", "Steam Vents", "Blood Crypt", "Overgrown Tomb",
        "Watery Grave", "Breeding Pool", "Stomping Ground", "Temple Garden",
        "Razorverge Thicket", "Cavern of Souls", "Blackcleave Cliffs",
        "Bleachbone Verge", "Shadowy Backstreet", "Dalkovan Encampment",
        "Venture Dive", "Secluded Courtyard", "Fiery Islet",
        "Spirebluff Canal", "Unclaimed Territory", "Arena of Glory",
        "Racecourse Furrows", "Horizon Canopy", "Inspiring Vantage",
        "Gemstone Caverns", "Spara's Headquarters", "Zagoth Crystal",
        "Sacred Peak", "Clearwater Pathway", "Darkbore Pathway",
        "Needleverge Pathway", "Riverglide Pathway", "Vizkpah Guildgate",
        "Razorfield Ruins", "Lair of the Hydra", "Hall of Storm Giants",
        "Boseiju, Who Endures", "Otawara, Soaring City",
        "Eiganjo, Seat of the Empire", "Sokenzan, Crucible of Defiance",
        "Mining Guideline", "Foundry of the Consulate",
        "Molten Tributary", "Razortide Bridge", "Jetmir's Garden",
        "Xander's Lounge", "Raffine's Tower", "Ziatora's Proving Ground",
        "Ketria", "Copperline Gorge", "Fastland", "Slowland",
        "Urza's Mine", "Urza's Power Plant", "Urza's Tower",
        "Eldrazi Temple", "Gruul Turf", "Simic Growth Chamber",
        "Boros Garrison", "Selesnya Sanctuary", "Dimir Aqueduct",
        "Tolaria West", "Flagstones of Trokair", "Murmuring Bosk",
        "Nest Robber", "Luminarch Aspirant",
    }

    for deck in decks:
        seen_in_deck = set()
        for card in deck["maindeck"]:
            name = card["name"]
            if name not in LANDS:
                card_counter[name] += card["qty"]
                if name not in seen_in_deck:
                    card_deck_count[name] += 1
                    seen_in_deck.add(name)

    total_decks = len(decks)
    result = []
    for name, qty in card_counter.most_common(n * 2):  # Get extra, filter lands
        if name in LANDS:
            continue
        ubiquity = round(card_deck_count[name] / total_decks, 3) if total_decks > 0 else 0
        result.append({
            "name": name,
            "total_qty": qty,
            "deck_count": card_deck_count[name],
            "ubiquity": ubiquity,
        })
        if len(result) >= n:
            break

    return result


def compute_deck_consistency(decks: list) -> float:
    """Compute how consistent decklists are within an archetype.

    Measures average Jaccard similarity of card sets across all deck pairs.
    High consistency (0.7+) = tight archetype with little variation.
    Low consistency (0.3-) = diverse builds under same label.
    """
    if len(decks) <= 1:
        return 1.0  # Single deck is trivially consistent

    # For efficiency, compute average overlap of each deck vs the "core" card set
    # (cards appearing in >=50% of decks)
    card_deck_count = Counter()
    for deck in decks:
        cards_in_deck = set(c["name"] for c in deck["maindeck"])
        for card in cards_in_deck:
            card_deck_count[card] += 1

    total = len(decks)
    core_cards = {c for c, cnt in card_deck_count.items() if cnt >= total * 0.5}

    if not core_cards:
        return 0.0

    # Average overlap ratio of each deck with the core
    overlaps = []
    for deck in decks:
        deck_cards = set(c["name"] for c in deck["maindeck"])
        overlap = len(deck_cards & core_cards) / len(core_cards)
        overlaps.append(overlap)

    return round(sum(overlaps) / len(overlaps), 3)


def compute_card_power_density(decks: list) -> float:
    """Compute how many format-staple cards appear in the archetype.

    Measures the density of competitive staples in maindeck.
    """
    if not decks:
        return 0.0

    staple_counts = []
    for deck in decks:
        md_cards = set(c["name"] for c in deck["maindeck"])
        staple_count = len(md_cards & FORMAT_STAPLES)
        staple_counts.append(staple_count / len(md_cards) if md_cards else 0)

    avg_density = sum(staple_counts) / len(staple_counts)
    # Scale: a deck with 20% staples ≈ 0.8, 10% ≈ 0.4, 5% ≈ 0.2
    return min(round(avg_density * 4, 3), 1.0)


def compute_metagame_share(deck_count: int, total_decks: int) -> float:
    """Compute metagame share from decklist counts."""
    if total_decks <= 0:
        return 0.0
    return round(deck_count / total_decks, 4)


def compute_performance_score(perf: dict) -> float:
    """Compute a normalized performance score from Goldfish placement data."""
    if not perf:
        return 0.0

    raw_score = perf.get("total_weighted_score", 0)
    max_reference = 2.5
    return min(round(raw_score / max_reference, 4), 1.0)


def compute_prevalence_confidence(deck_count: int) -> float:
    """Compute confidence based on sample size (logarithmic scaling)."""
    if deck_count <= 0:
        return 0.0
    return min(round(0.3 + 0.7 * (math.log10(deck_count) / math.log10(300)), 4), 1.0)


def compute_tournament_win_indicator(wins: int, top8_count: int) -> float:
    """Compute tournament win indicator from Goldfish data."""
    if wins <= 0 and top8_count <= 0:
        return 0.0
    score = min(wins * 0.5, 1.0) + min(top8_count * 0.05, 0.3)
    return min(round(score, 4), 1.0)


def compute_strength_score(metagame_share: float, perf_score: float,
                               consistency: float, power_density: float,
                               win_indicator: float) -> float:
    """Compute final weighted strength score (0-100 scale)."""
    weights = {
        "metagame_share": 0.35,
        "performance": 0.30,
        "consistency": 0.15,
        "power_density": 0.10,
        "tournament_wins": 0.10,
    }

    raw = (
        weights["metagame_share"] * min(metagame_share * 10, 1.0)
        + weights["performance"] * perf_score
        + weights["consistency"] * consistency
        + weights["power_density"] * power_density
        + weights["tournament_wins"] * win_indicator
    )
    return round(raw * 100, 1)


def assign_tier(score: float, share: float) -> str:
    """Assign competitive tier based on strength score and metagame share."""
    if score >= 50 or share >= 0.08:
        return "Tier 1"
    elif score >= 25 or share >= 0.03:
        return "Tier 2"
    elif score >= 10 or share >= 0.01:
        return "Tier 3"
    else:
        return "Tier 4"


# ─── Data Loading ────────────────────────────────────────────────────────────

def load_banlist() -> set:
    """Load current Modern banlist."""
    ban_file = Path("mtg_modern_data/ban_list/current.json")
    if not ban_file.exists():
        return set()
    with open(ban_file) as f:
        data = json.load(f)
    return set(data.get("banned", []))


def load_decklist_data():
    """Load and merge decklist data from Top8 and Goldfish sources.
    
    Top8 is primary; Goldfish supplements archetypes/decklists not in Top8.
    Deduplication: skip Goldfish decks whose (event_name, player) already exists in Top8.
    """
    decklist_dir = Path("mtg_modern_data/decks/raw/decklists")

    # Load Top8 decklists (primary)
    top8_data = None
    top8_files = sorted(decklist_dir.glob("*_top8_decklists.json"), reverse=True)
    if top8_files:
        with open(top8_files[0]) as f:
            top8_data = json.load(f)

    # Load Goldfish decklists (supplementary)
    gf_deck_data = None
    gf_deck_files = sorted(decklist_dir.glob("*_goldfish_decklists.json"), reverse=True)
    if gf_deck_files:
        with open(gf_deck_files[0]) as f:
            gf_deck_data = json.load(f)

    if not top8_data and not gf_deck_data:
        return None

    # If only one source, return it directly
    if not gf_deck_data:
        return top8_data
    if not top8_data:
        return gf_deck_data

    # Merge: Top8 is primary, Goldfish supplements
    # Build dedup signatures from Top8: (event_name_lower, player_lower) per archetype
    top8_sigs = set()
    for deck in top8_data.get("decklists", []):
        sig = (deck.get("event_name", "").lower(), deck.get("player", "").lower())
        top8_sigs.add(sig)

    # Also match by archetype canonical name
    top8_arch_players = defaultdict(set)
    for deck in top8_data.get("decklists", []):
        canon = normalize_archetype_name(deck.get("deck_name", ""))
        top8_arch_players[canon].add(deck.get("player", "").lower())

    # Add Goldfish decks that don't overlap and are legal
    gf_decks_added = 0
    gf_decks_skipped = 0
    gf_decks_illegal = 0
    # Filter Top8 decklists to legal only
    merged_decklists = [d for d in top8_data.get("decklists", [])
                        if d.get("legality", {}).get("legal", True)]
    top8_illegal = len(top8_data.get("decklists", [])) - len(merged_decklists)

    for deck in gf_deck_data.get("decklists", []):
        # Skip illegal decks (contains banned cards)
        if not deck.get("legality", {}).get("legal", True):
            gf_decks_illegal += 1
            continue

        canon = GOLDFISH_TO_CANONICAL.get(deck.get("deck_name", ""), deck.get("deck_name", ""))
        # Also try the deck_name_canonical field
        if deck.get("deck_name_canonical"):
            canon = deck["deck_name_canonical"]

        player_lower = deck.get("player", "").lower()
        event_lower = deck.get("event_name", "").lower()

        # Skip if exact (event, player) match in Top8
        if (event_lower, player_lower) in top8_sigs:
            gf_decks_skipped += 1
            continue

        # Skip if same archetype + same player in Top8 (likely same deck)
        if canon in top8_arch_players and player_lower in top8_arch_players[canon]:
            gf_decks_skipped += 1
            continue

        # Normalize the deck_name to canonical before adding
        deck_copy = dict(deck)
        if canon != deck_copy.get("deck_name"):
            deck_copy["deck_name_raw"] = deck_copy["deck_name"]
            deck_copy["deck_name"] = canon

        merged_decklists.append(deck_copy)
        gf_decks_added += 1

    total_decks = len(merged_decklists)
    illegal_decks = top8_illegal + gf_decks_illegal

    merged = {
        "format": "Modern",
        "collected_date": top8_data.get("collected_date", ""),
        "source": "MTGTop8+Goldfish",
        "period_start": top8_data.get("period_start", gf_deck_data.get("period_start", "")),
        "total_decks": total_decks,
        "illegal_decks_filtered": illegal_decks,
        "top8_decks": top8_data.get("total_decks", 0),
        "goldfish_decks": gf_deck_data.get("total_decks", 0),
        "goldfish_added": gf_decks_added,
        "goldfish_skipped_overlap": gf_decks_skipped,
        "goldfish_illegal": gf_decks_illegal,
        "decklists": merged_decklists,
    }

    print(f"  Decklist merge: Top8={top8_data.get('total_decks', 0)}"
          f"({top8_illegal} illegal), "
          f"Goldfish={gf_deck_data.get('total_decks', 0)}"
          f"({gf_decks_illegal} illegal), "
          f"GF added={gf_decks_added}, GF skipped={gf_decks_skipped}")
    print(f"  Total legal decks: {total_decks}")

    return merged


def load_goldfish_data():
    """Load Goldfish data for performance/placement info."""
    raw_dir = Path("mtg_modern_data/decks/raw")
    gf_files = sorted(raw_dir.glob("*_goldfish.json"), reverse=True)
    if not gf_files:
        return None
    with open(gf_files[0]) as f:
        return json.load(f)


def load_top8_aggregate_data():
    """Load Top8 aggregate data for cross-reference."""
    raw_dir = Path("mtg_modern_data/decks/raw")
    t8_files = sorted(raw_dir.glob("*_mtgtop8.json"), reverse=True)
    if not t8_files:
        return None
    with open(t8_files[0]) as f:
        return json.load(f)


# ─── Goldfish Archetype Mapping ──────────────────────────────────────────────
# Maps Goldfish names to our canonical archetype names

GOLDFISH_TO_CANONICAL = {
    "Belcher": "Landless",
    "Boros Energy": "Boros Energy",
    "Neobrand": "Allosaurus Combo",
    "Esper GenericBlink": "Blink",
    "Azorius GenericBlink": "Blink",
    "Gruul Basking Broodscale Combo": "Broodscale Bloodchief",
    "Mono-Green Basking Broodscale Combo": "Broodscale Bloodchief",
    "Goryo's Vengeance": "Goryo's Vengeance",
    "Izzet Affinity": "Affinity",
    "Izzet Prowess": "UR Prowess",
    "Crashing Footfalls": "Crashing Footfalls",
    "Domain Zoo": "4/5c Aggro",
    "Mardu Energy": "Mardu Aggro",
    "Boros Burn": "Red Deck Wins",
    "4c Energy": "4/5c Aggro",
    "Esper Murktide": "Death's Shadow",
    "Amulet Titan": "Amulet Titan",
    "Merfolk": "Merfolk",
    "WU": "UW Control",
    "BR": "Mono-Black Midrange",
    "G": "Birthing Ritual",
    "WR": "Red Deck Wins",
    "Izzet": "UR Prowess",
    "Eldrazi": "Eldrazi Ramp",
    "Temur": "4/5c Aggro",
    "Temur Midrange": "4/5c Aggro",
    "Yawgmoth Combo": "Yawgmoth",
    "Living End": "Living End",
    "Affinity": "Affinity",
    "UW Control": "UW Control",
    "Ruby Storm": "Ruby Storm",
    "Dimir Control": "Dimir Control",
    "Dredge": "Dredge",
    "Hammer Time": "Hammer Time",
    "Creativity": "Creativity",
    "Tron": "UW Tron",
    "Eldrazi Tron": "Eldrazi Tron",
    "Amulet": "Amulet Titan",
    "Prowess": "UR Prowess",
    "Burn": "Red Deck Wins",
    "Mill": "UB Mill",
    "Shadow": "Death's Shadow",
    "Underworld Cookbook": "The Underworld Cookbook",
    "Cascade Crash": "Cascade Crash",
    "Boros Ponza": "Boros Ponza",
    "Reanimator": "Reanimator",
    "Instant Reanimator": "Instant Reanimator",
    "Death's Shadow": "Death's Shadow",
    "Broodscale Combo": "Broodscale Bloodchief",
}


# ─── Main Evaluation Logic ──────────────────────────────────────────────────

def build_archetype_from_decklists(decklist_data: dict, gf_data: dict,
                                     t8_agg_data: dict, banlist: set) -> list:
    """Build archetype entries from actual decklist data, fused with Goldfish."""

    decklists = decklist_data["decklists"]
    total_decks = len(decklists)

    # Step 1: Group decklists by canonical archetype name
    arch_decks = defaultdict(list)
    for deck in decklists:
        canon = normalize_archetype_name(deck["deck_name"])
        arch_decks[canon].append(deck)

    print(f"Decklist archetypes after normalization: {len(arch_decks)}")
    for name, decks in sorted(arch_decks.items(), key=lambda x: -len(x[1])):
        print(f"  {len(decks):3d}x {name}")

    # Step 2: Build Goldfish lookup by canonical name
    gf_lookup = {}
    if gf_data:
        for arch in gf_data.get("archetypes", []):
            canon = GOLDFISH_TO_CANONICAL.get(arch["name"], arch["name"])
            existing = gf_lookup.get(canon)
            if existing:
                existing["metagame_share"] += arch["metagame_share"]
                existing["deck_count"] += arch.get("deck_count", 0)
                perf = arch.get("performance", {})
                for k in ["total_weighted_score", "top8_count", "league_5_0_count", "wins"]:
                    existing["performance"][k] = existing["performance"].get(k, 0) + perf.get(k, 0)
            else:
                gf_lookup[canon] = {
                    "metagame_share": arch["metagame_share"],
                    "metagame_share_corrected": arch.get("metagame_share_corrected",
                                                          arch["metagame_share"] * 0.65),
                    "deck_count": arch.get("deck_count", 0),
                    "key_cards": arch.get("key_cards", []),
                    "performance": dict(arch.get("performance", {})),
                }

    # Step 3: Build Top8 aggregate lookup
    t8_lookup = {}
    if t8_agg_data:
        for arch in t8_agg_data.get("archetypes", []):
            canon = normalize_archetype_name(arch["name"])
            existing = t8_lookup.get(canon)
            if existing:
                existing["metagame_share"] = max(existing["metagame_share"], arch["metagame_share"])
                existing["deck_count"] += arch.get("deck_count", 0)
            else:
                t8_lookup[canon] = {
                    "metagame_share": arch["metagame_share"],
                    "deck_count": arch.get("deck_count", 0),
                }

    # Step 4: Build fused archetype entries (three-phase: raw → normalize → score)
    all_canonical = set(arch_decks.keys()) | set(gf_lookup.keys()) | set(t8_lookup.keys())

    # ── Phase 1: Collect all raw fused shares (un-normalized) ──
    raw_entries = []
    for name in all_canonical:
        decks = arch_decks.get(name, [])
        gf = gf_lookup.get(name, {})
        t8 = t8_lookup.get(name, {})

        # --- Metagame Share (raw) ---
        decklist_share = compute_metagame_share(len(decks), total_decks)
        top8_share = t8.get("metagame_share", 0)
        gf_raw_share = gf.get("metagame_share", 0)
        gf_corrected = gf.get("metagame_share_corrected", gf_raw_share * 0.65)

        if decks:
            raw_fused_share = decklist_share
            if top8_share > decklist_share * 1.5:
                raw_fused_share = round(decklist_share * 0.7 + top8_share * 0.3, 4)
        elif t8 or gf:
            if t8 and gf:
                raw_fused_share = round(0.6 * top8_share + 0.4 * gf_corrected, 4)
            elif gf:
                raw_fused_share = gf_corrected
            else:
                raw_fused_share = top8_share
        else:
            raw_fused_share = 0.0

        raw_entries.append({
            "name": name,
            "decks": decks,
            "gf": gf,
            "t8": t8,
            "decklist_share": decklist_share,
            "top8_share": top8_share,
            "gf_raw_share": gf_raw_share,
            "gf_corrected": gf_corrected,
            "raw_fused_share": raw_fused_share,
        })

    # ── Phase 2: Global normalization — ensure Σ fused_metagame_share = 1.0 ──
    total_raw_share = sum(e["raw_fused_share"] for e in raw_entries)
    if total_raw_share > 0:
        for e in raw_entries:
            e["fused_metagame_share"] = round(e["raw_fused_share"] / total_raw_share, 4)
    else:
        for e in raw_entries:
            e["fused_metagame_share"] = 0.0

    # Verify normalization
    normalized_total = sum(e["fused_metagame_share"] for e in raw_entries)
    print(f"  Normalization: raw_total={total_raw_share:.4f} → normalized_total={normalized_total:.4f}")

    # ── Phase 3: Compute scores using normalized shares ──
    fused = []
    for e in raw_entries:
        name = e["name"]
        decks = e["decks"]
        gf = e["gf"]
        t8 = e["t8"]
        fused_share = e["fused_metagame_share"]
        decklist_share = e["decklist_share"]
        top8_share = e["top8_share"]
        gf_raw_share = e["gf_raw_share"]
        gf_corrected = e["gf_corrected"]

        # --- Key Cards (from actual decklists) ---
        if decks:
            key_cards_data = extract_key_cards(decks, n=5)
            key_cards = [kc["name"] for kc in key_cards_data]
        else:
            raw_kc = gf.get("key_cards", [])
            banned_in_key = [c for c in raw_kc if c in banlist]
            key_cards = [c for c in raw_kc if c not in banlist]

        # --- Performance Score (from Goldfish) ---
        perf_data = gf.get("performance", {})
        perf_score = compute_performance_score(perf_data)

        # --- Deck Consistency (from decklists) ---
        if decks:
            consistency = compute_deck_consistency(decks)
        else:
            consistency = 0.5  # Default for aggregate-only

        # --- Card Power Density ---
        if decks:
            power_density = compute_card_power_density(decks)
        else:
            power_density = 0.3  # Default

        # --- Tournament Win Indicator ---
        wins = perf_data.get("wins", 0)
        top8_count = perf_data.get("top8_count", 0)
        win_indicator = compute_tournament_win_indicator(wins, top8_count)

        # --- Prevalence Confidence ---
        deck_count = len(decks) + t8.get("deck_count", 0) + gf.get("deck_count", 0)
        prevalence = compute_prevalence_confidence(deck_count)

        # --- Final Strength Score (using normalized share) ---
        strength = compute_strength_score(
            fused_share, perf_score, consistency, power_density, win_indicator
        )

        # --- Tier ---
        tier = assign_tier(strength, fused_share)

        # --- Category ---
        category = CATEGORY_MAP.get(name, "unknown")

        # Build entry
        entry = {
            "name": name,
            "category": category,
            "decklist_count": len(decks),
            "fused_metagame_share": fused_share,
            "key_cards": key_cards,
            "key_cards_detail": extract_key_cards(decks, n=5) if decks else None,
            "sources": {
                "decklists": {
                    "count": len(decks),
                    "share": decklist_share,
                } if decks else None,
                "mtgtop8": {
                    "metagame_share": top8_share,
                    "deck_count": t8.get("deck_count", 0),
                } if t8 else None,
                "goldfish": {
                    "metagame_share_raw": gf_raw_share,
                    "metagame_share_corrected": gf_corrected,
                    "deck_count": gf.get("deck_count", 0),
                } if gf else None,
            },
            "deck_consistency": consistency,
            "card_power_density": power_density,
            "performance": {
                "score": perf_score,
                "detail": perf_data if perf_data else None,
            },
            "prevalence_confidence": prevalence,
            "tournament_win_indicator": win_indicator,
            "strength_score": strength,
            "tier": tier,
        }

        fused.append(entry)

    # Sort by strength score descending
    fused.sort(key=lambda x: x["strength_score"], reverse=True)
    return fused


def main():
    banlist = load_banlist()
    if banlist:
        print(f"Banlist loaded: {len(banlist)} banned cards")

    decklist_data = load_decklist_data()
    gf_data = load_goldfish_data()
    t8_agg_data = load_top8_aggregate_data()

    if not decklist_data and not gf_data and not t8_agg_data:
        print("Error: No data found. Run scrapers first.")
        sys.exit(1)

    print(f"Data loaded:")
    if decklist_data:
        print(f"  Decklists: {decklist_data['total_decks']} decks "
              f"(Top8={decklist_data.get('top8_decks', '?')}, "
              f"Goldfish={decklist_data.get('goldfish_decks', 0)})")
        if decklist_data.get("goldfish_added"):
            print(f"  Goldfish supplement: +{decklist_data['goldfish_added']} decks, "
                  f"{decklist_data.get('goldfish_skipped_overlap', 0)} overlap skipped")
    else:
        print(f"  Decklists: 0 decks")
    print(f"  Goldfish aggregate: {'yes' if gf_data else 'no'}")
    print(f"  Top8 aggregate: {'yes' if t8_agg_data else 'no'}")
    print()

    # Build fused archetypes
    fused = build_archetype_from_decklists(decklist_data, gf_data, t8_agg_data, banlist)

    # Output paths
    processed_dir = Path("mtg_modern_data/decks/processed")
    processed_dir.mkdir(parents=True, exist_ok=True)
    top_n_dir = Path("mtg_modern_data/decks/top_n")
    top_n_dir.mkdir(parents=True, exist_ok=True)

    # Write full fused data
    fused_output = {
        "format": "Modern",
        "version": "2.0",
        "model": "decklist-based",
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "period_start": decklist_data.get("period_start",
                         gf_data.get("period_start",
                         t8_agg_data.get("period_start", "unknown"))),
        "fusion_config": {
            "score_weights": {
                "metagame_share": 0.35,
                "performance": 0.30,
                "consistency": 0.15,
                "power_density": 0.10,
                "tournament_wins": 0.10,
            },
            "data_sources": ["decklists", "goldfish", "mtgtop8_aggregate"],
        },
        "total_archetypes": len(fused),
        "decklist_sample_size": decklist_data.get("total_decks", 0) if decklist_data else 0,
        "tier_distribution": {},
        "category_distribution": {},
        "archetypes": fused,
    }

    # Compute distributions
    for arch in fused:
        tier = arch["tier"]
        fused_output["tier_distribution"][tier] = fused_output["tier_distribution"].get(tier, 0) + 1
        cat = arch["category"]
        fused_output["category_distribution"][cat] = fused_output["category_distribution"].get(cat, 0) + 1

    fused_file = processed_dir / "fused_archetypes.json"
    with open(fused_file, "w", encoding="utf-8") as f:
        json.dump(fused_output, f, indent=2, ensure_ascii=False)
    print(f"\nFused data: {fused_file}")
    print(f"  Total archetypes: {len(fused)}")
    print(f"  Tier distribution: {fused_output['tier_distribution']}")
    print(f"  Category distribution: {fused_output['category_distribution']}")

    # Write Top N
    top_n = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 15
    top_decks = fused[:top_n]

    top_output = {
        "format": "Modern",
        "version": "2.0",
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "period_start": fused_output["period_start"],
        "top_n": top_n,
        "ranking_criteria": (
            "strength_score = 0.35*fused_share + 0.30*performance "
            "+ 0.15*consistency + 0.10*power_density + 0.10*wins"
        ),
        "decks": [],
    }

    for i, deck in enumerate(top_decks, 1):
        top_output["decks"].append({
            "rank": i,
            "name": deck["name"],
            "tier": deck["tier"],
            "category": deck["category"],
            "strength_score": deck["strength_score"],
            "fused_metagame_share": deck["fused_metagame_share"],
            "decklist_count": deck["decklist_count"],
            "key_cards": deck["key_cards"],
            "deck_consistency": deck["deck_consistency"],
            "card_power_density": deck["card_power_density"],
            "performance_score": deck["performance"]["score"],
            "wins": deck["performance"]["detail"].get("wins", 0) if deck["performance"]["detail"] else 0,
        })

    top_file = top_n_dir / "top_decks.json"
    with open(top_file, "w", encoding="utf-8") as f:
        json.dump(top_output, f, indent=2, ensure_ascii=False)
    print(f"\nTop {top_n}: {top_file}")

    # Print summary table
    print(f"\n{'='*90}")
    print(f"{'Rank':<5}{'Deck':<22}{'Tier':<8}{'Score':<8}{'Share':<8}"
          f"{'Decks':<7}{'Cons':<7}{'Pow':<7}{'Perf':<8}{'Wins':<6}")
    print(f"{'-'*90}")
    for i, deck in enumerate(top_decks, 1):
        wins = deck["performance"]["detail"].get("wins", 0) if deck["performance"]["detail"] else 0
        print(f"{i:<5}{deck['name']:<22}{deck['tier']:<8}{deck['strength_score']:<8.1f}"
              f"{deck['fused_metagame_share']:<8.1%}{deck['decklist_count']:<7}"
              f"{deck['deck_consistency']:<7.2f}{deck['card_power_density']:<7.2f}"
              f"{deck['performance']['score']:<8.2f}{wins:<6}")

    # Print all tiers
    print(f"\n{'='*90}")
    print("Full Tier Breakdown:")
    for tier_name in ["Tier 1", "Tier 2", "Tier 3", "Tier 4"]:
        tier_decks = [d for d in fused if d["tier"] == tier_name]
        if tier_decks:
            names = ", ".join(f"{d['name']}({d['decklist_count']})" for d in tier_decks)
            print(f"  {tier_name} ({len(tier_decks)}): {names}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Schema Validation Script for MTG Modern Data

Validates data files against their JSON Schema definitions.
Checks for field consistency, naming conventions, and structural correctness.

Usage:
  python3 scripts/validate_schema.py [--fix]
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path("mtg_modern_data")
SCHEMAS_DIR = DATA_DIR / "schemas"


def validate_archetype_stats(filepath: Path) -> list:
    """Validate archetype aggregate files against schema conventions."""
    errors = []
    with open(filepath) as f:
        data = json.load(f)

    # Required top-level fields
    for field in ["format", "collected_date", "source", "period_start", "data_timeframe", "total_decks"]:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Source must be valid
    if data.get("source") not in ("MTGGoldfish", "MTGTop8"):
        errors.append(f"Invalid source: {data.get('source')}")

    # Check archetypes
    for i, arch in enumerate(data.get("archetypes", [])):
        # Must have deck_count (not estimated_decks)
        if "estimated_decks" in arch:
            errors.append(f"archetypes[{i}]: uses deprecated 'estimated_decks', should be 'deck_count'")
        if "deck_count" not in arch:
            errors.append(f"archetypes[{i}]: missing 'deck_count'")

        # Category must be valid
        if arch.get("category") not in ("aggro", "control", "combo", "midrange"):
            errors.append(f"archetypes[{i}] '{arch.get('name')}': invalid category '{arch.get('category')}'")

    # Check events don't have redundant 'level' field
    for i, event in enumerate(data.get("events", [])):
        if "level" in event and "tier" in event:
            errors.append(f"events[{i}]: has both 'level' and 'tier' (redundant, remove 'level')")

    # data_timeframe should be consistent
    if data.get("data_timeframe") == "last_2_weeks":
        errors.append("data_timeframe='last_2_weeks' is deprecated, use '14_days'")

    return errors


def validate_decklist_entry(filepath: Path) -> list:
    """Validate decklist files against schema conventions."""
    errors = []
    with open(filepath) as f:
        data = json.load(f)

    for i, deck in enumerate(data.get("decklists", [])):
        # Must have source
        if "source" not in deck:
            errors.append(f"decklists[{i}]: missing 'source'")

        # event_date should be ISO format (YYYY-MM-DD)
        event_date = deck.get("event_date", "")
        if event_date and "/" in event_date:
            errors.append(f"decklists[{i}]: event_date='{event_date}' is not ISO format (expected YYYY-MM-DD)")

        # Must have deck_name_canonical
        if "deck_name_canonical" not in deck:
            errors.append(f"decklists[{i}]: missing 'deck_name_canonical' (deck_name='{deck.get('deck_name')}')")

        # Maindeck structure
        for j, card in enumerate(deck.get("maindeck", [])):
            if "qty" not in card or "name" not in card:
                errors.append(f"decklists[{i}].maindeck[{j}]: missing 'qty' or 'name'")

        # Sideboard structure
        for j, card in enumerate(deck.get("sideboard", [])):
            if "qty" not in card or "name" not in card:
                errors.append(f"decklists[{i}].sideboard[{j}]: missing 'qty' or 'name'")

    # Check illegal_decks for duplicates
    illegal = data.get("legality_report", {}).get("illegal_decks", [])
    seen = set()
    for entry in illegal:
        sig = (entry.get("deck_name", ""), entry.get("player", ""), str(entry.get("banned_cards", "")))
        if sig in seen:
            errors.append(f"illegal_decks: duplicate entry for {entry.get('deck_name')} by {entry.get('player')}")
        seen.add(sig)

    return errors


def validate_fused_archetypes(filepath: Path) -> list:
    """Validate fused_archetypes.json — metagame share normalization and field consistency."""
    errors = []
    with open(filepath) as f:
        data = json.load(f)

    # Check normalization: sum should be ~1.0
    shares = [a["fused_metagame_share"] for a in data.get("archetypes", [])]
    total = sum(shares)
    if abs(total - 1.0) > 0.02:
        errors.append(f"fused_metagame_share sum = {total:.4f}, expected ~1.0 (normalization issue)")

    # Check each archetype
    for i, arch in enumerate(data.get("archetypes", [])):
        # Must have sources with deck_count (not estimated_decks)
        t8_src = arch.get("sources", {}).get("mtgtop8", {})
        if t8_src and "estimated_decks" in t8_src:
            errors.append(f"archetypes[{i}]: mtgtop8 source uses deprecated 'estimated_decks'")

        # Category check
        if arch.get("category") not in ("aggro", "control", "combo", "midrange", "unknown"):
            errors.append(f"archetypes[{i}] '{arch.get('name')}': invalid category '{arch.get('category')}'")

    return errors


def main():
    all_errors = {}

    # Validate archetype aggregate files
    raw_dir = DATA_DIR / "decks" / "raw"
    for f in sorted(raw_dir.glob("*_goldfish.json")) + sorted(raw_dir.glob("*_mtgtop8.json")):
        errs = validate_archetype_stats(f)
        if errs:
            all_errors[str(f)] = errs

    # Validate decklist files
    decklist_dir = raw_dir / "decklists"
    for f in sorted(decklist_dir.glob("*_decklists.json")):
        errs = validate_decklist_entry(f)
        if errs:
            all_errors[str(f)] = errs

    # Validate fused archetypes
    fused_file = DATA_DIR / "decks" / "processed" / "fused_archetypes.json"
    if fused_file.exists():
        errs = validate_fused_archetypes(fused_file)
        if errs:
            all_errors[str(fused_file)] = errs

    # Report
    if all_errors:
        print(f"❌ Found issues in {len(all_errors)} file(s):\n")
        for filepath, errs in all_errors.items():
            print(f"  {filepath}")
            for e in errs:
                print(f"    - {e}")
            print()
        sys.exit(1)
    else:
        print("✅ All data files pass schema validation.")
        sys.exit(0)


if __name__ == "__main__":
    main()

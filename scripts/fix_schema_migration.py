#!/usr/bin/env python3
"""Fix existing data files to match unified schema."""
import json
from pathlib import Path

# 1. Fix mtgtop8 aggregate: estimated_decks -> deck_count, data_timeframe, level removal
f = Path("mtg_modern_data/decks/raw/2026-05-27_mtgtop8.json")
data = json.loads(f.read_text())

if data.get("data_timeframe") == "last_2_weeks":
    data["data_timeframe"] = "14_days"

for arch in data.get("archetypes", []):
    if "estimated_decks" in arch:
        arch["deck_count"] = arch.pop("estimated_decks")

for event in data.get("events", []):
    if "level" in event and "tier" in event:
        del event["level"]

f.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print("Fixed mtgtop8 aggregate")

# 2. Fix top8 decklists: add deck_name_canonical, fix event_date format
NORM = {
    "UrzaTron": "UW Tron", "Urzatron": "UW Tron", "Uw Control": "UW Control", "Ub Mill": "UB Mill",
    "Izzet Affinity": "Affinity", "Pinnacle Affinity": "Affinity",
    "Izzet Prowess": "UR Prowess", "UR Cutter Prowess": "UR Prowess", "Prowess": "UR Prowess",
    "Landless Belcher": "Landless", "Goblins Combo": "Landless",
    "Boros Aggro": "Boros Energy", "Jeskai Energy": "Boros Energy",
    "Domain Rhinos": "Crashing Footfalls",
    "Simic Birthing Ritual": "Birthing Ritual", "Simic Ritual": "Birthing Ritual",
    "Mono Green Aggro": "Mono-G Aggro", "Mono": "Mono-Black Midrange",
    "Azorius Blink": "Blink", "Orzhov Blink": "Blink", "Esper Blink": "Blink",
    "Mardu Blink": "Blink", "Domain Blink": "Blink",
    "Frog Legs": "Frog Combo",
    "Grixis Death Shadow": "Death's Shadow",
    "Samwise Combo": "Yawgmoth", "Burn": "Red Deck Wins",
    "Chord Toolbox": "Creatures Toolbox", "Scepter Chant": "UW Control",
    "Soultrader": "Sacrifice Combo",
}

f2 = Path("mtg_modern_data/decks/raw/decklists/2026-05-27_top8_decklists.json")
data2 = json.loads(f2.read_text())

for deck in data2.get("decklists", []):
    if "deck_name_canonical" not in deck:
        deck["deck_name_canonical"] = NORM.get(deck.get("deck_name", ""), deck.get("deck_name", ""))
    ed = deck.get("event_date", "")
    if ed and "/" in ed:
        try:
            parts = ed.split("/")
            deck["event_date"] = f"20{parts[2]}-{parts[1]}-{parts[0]}"
        except (IndexError, ValueError):
            pass

f2.write_text(json.dumps(data2, indent=2, ensure_ascii=False))
print("Fixed top8 decklists")

# 3. Fix goldfish decklists: deduplicate illegal_decks
f3 = Path("mtg_modern_data/decks/raw/decklists/2026-05-28_goldfish_decklists.json")
data3 = json.loads(f3.read_text())

illegal = data3.get("legality_report", {}).get("illegal_decks", [])
if illegal:
    seen = {}
    deduped = []
    for entry in illegal:
        sig = (entry.get("deck_name", ""), entry.get("player", ""), str(entry.get("banned_cards", "")))
        if sig not in seen:
            seen[sig] = entry
            deduped.append(entry)
    data3["legality_report"]["illegal_decks"] = deduped
    f3.write_text(json.dumps(data3, indent=2, ensure_ascii=False))
    print(f"Fixed goldfish decklists: {len(illegal)} -> {len(deduped)} illegal_decks")
else:
    print("goldfish decklists: no illegal_decks to fix")

print("\nDone!")

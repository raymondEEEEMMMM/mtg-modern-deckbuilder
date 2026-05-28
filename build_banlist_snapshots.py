#!/usr/bin/env python3
"""
Build complete banlist snapshots from MTG Fandom Timeline events.
Each snapshot is a full banlist at a given date, computed by applying changes cumulatively.
"""

import json
from datetime import datetime
from pathlib import Path

# Timeline events extracted from MTG Fandom Wiki (Banned_and_restricted_cards/Timeline)
# Verified against official Wizards B&R announcements
# Format: (effective_date, added_list, removed_list)
TIMELINE = [
    ("2011-09-20", ["Blazing Shoal", "Cloudpost", "Green Sun's Zenith", "Ponder", "Preordain", "Rite of Flame"], []),
    ("2011-12-20", ["Punishing Fire", "Wild Nacatl"], []),
    ("2012-09-20", [], ["Valakut, the Molten Pinnacle"]),
    ("2013-01-28", ["Bloodbraid Elf", "Seething Song"], []),
    ("2013-05-16", ["Second Sunrise"], []),
    ("2014-02-03", ["Deathrite Shaman"], ["Bitterblossom", "Wild Nacatl"]),
    ("2015-01-19", ["Dig Through Time", "Treasure Cruise", "Birthing Pod"], ["Golgari Grave-Troll"]),
    ("2016-01-18", ["Splinter Twin", "Summer Bloom"], []),
    ("2016-04-04", ["Eye of Ugin"], ["Ancestral Vision", "Sword of the Meek"]),
    ("2017-01-09", ["Gitaxian Probe", "Golgari Grave-Troll"], []),
    ("2018-02-19", [], ["Jace, the Mind Sculptor", "Bloodbraid Elf"]),
    ("2019-01-28", ["Krark-Clan Ironworks"], []),
    ("2019-07-08", ["Bridge from Below"], []),
    ("2019-08-26", ["Hogaak, Arisen Necropolis", "Faithless Looting"], ["Stoneforge Mystic"]),
    ("2020-01-13", ["Oko, Thief of Crowns", "Mox Opal", "Mycosynth Lattice"], []),
    ("2020-03-16", ["Once Upon a Time"], []),
    ("2020-07-06", ["Arcum's Astrolabe"], []),
    ("2021-02-15", ["Field of the Dead", "Mystic Sanctuary", "Simian Spirit Guide", "Tibalt's Trickery", "Uro, Titan of Nature's Wrath"], []),
    ("2022-03-07", ["Lurrus of the Dream-Den"], []),
    ("2022-10-10", ["Yorion, Sky Nomad"], []),
    ("2023-08-07", [], ["Preordain"]),
    ("2023-12-04", ["Fury", "Up the Beanstalk"], []),
    ("2024-03-11", ["Violent Outburst"], []),
    ("2024-08-26", ["Grief", "Nadu, Winged Wisdom"], []),
    ("2024-12-09", ["Amped Raptor", "Jegantha, the Wellspring", "The One Ring"], ["Faithless Looting", "Green Sun's Zenith", "Mox Opal", "Splinter Twin"]),
    ("2025-03-10", ["Underworld Breach"], []),
    ("2026-05-18", ["Phlage, Titan of Fire's Fury", "Lotus Field"], ["Violent Outburst", "Umezawa's Jitte"]),
]

# Sort chronologically
TIMELINE.sort(key=lambda x: x[0])

# Initial banlist (2011-08-01 baseline)
BASELINE = [
    "Ancestral Vision",
    "Ancient Den",
    "Bitterblossom",
    "Chrome Mox",
    "Dark Depths",
    "Dread Return",
    "Glimpse of Nature",
    "Golgari Grave-Troll",
    "Great Furnace",
    "Hypergenesis",
    "Jace, the Mind Sculptor",
    "Mental Misstep",
    "Seat of the Synod",
    "Sensei's Divining Top",
    "Skullclamp",
    "Stoneforge Mystic",
    "Sword of the Meek",
    "Tree of Tales",
    "Umezawa's Jitte",
    "Valakut, the Molten Pinnacle",
    "Vault of Whispers",
]

def build_snapshot(baseline, events):
    """Build snapshots by applying events cumulatively."""
    snapshots = []
    banned = set(baseline)

    # Add baseline snapshot
    snapshots.append({
        "effective_date": "2011-08-01",
        "format": "Modern",
        "description": "Modern format initial banlist",
        "is_baseline": True,
        "banned": sorted(list(banned)),
        "restricted": [],
        "deck_banned": [],
        "total": len(banned),
    })

    for date, added, removed in events:
        for card in added:
            banned.add(card)
        for card in removed:
            banned.discard(card)

        snapshots.append({
            "effective_date": date,
            "format": "Modern",
            "description": f"B&R update {date}",
            "is_baseline": False,
            "banned": sorted(list(banned)),
            "restricted": [],
            "deck_banned": [],
            "total": len(banned),
            "changes": {
                "added": sorted(added) if added else [],
                "removed": sorted(removed) if removed else [],
            }
        })

    return snapshots

def main():
    history_dir = Path("mtg_modern_data/ban_list/history")
    history_dir.mkdir(parents=True, exist_ok=True)

    snapshots = build_snapshot(BASELINE, TIMELINE)

    # Save each snapshot
    for snap in snapshots:
        date = snap["effective_date"]
        fname = f"{date}.json" if snap["is_baseline"] else f"{date}.json"
        path = history_dir / fname
        with open(path, 'w') as f:
            json.dump(snap, f, indent=2)
        print(f"Saved: {path.name} - {snap['total']} banned cards")

    # Update meta.json
    changes_history = []
    for snap in snapshots:
        if not snap["is_baseline"]:
            changes_history.append({
                "effective_date": snap["effective_date"],
                "description": snap["description"],
                "file": f"{snap['effective_date']}.json",
                "is_baseline": False,
                "changes": snap.get("changes", {"added": [], "removed": []})
            })

    meta = {
        "format": "Modern",
        "last_updated": datetime.now().isoformat(),
        "data_range": {
            "start": "2011-08-01",
            "end": snapshots[-1]["effective_date"]
        },
        "total_snapshots": len(snapshots),
        "changes_history": [
            {"effective_date": "2011-08-01", "description": "Modern format initial banlist", "file": "2011-08-01.json", "is_baseline": True}
        ] + changes_history
    }

    with open("mtg_modern_data/ban_list/meta.json", 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"\nTotal snapshots: {len(snapshots)}")
    print(f"Date range: {snapshots[0]['effective_date']} to {snapshots[-1]['effective_date']}")

if __name__ == "__main__":
    main()
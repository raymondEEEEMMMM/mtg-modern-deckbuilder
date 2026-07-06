#!/usr/bin/env python3
"""
Aggregate sideboard card frequency + per-archetype winrate from already-scraped
decklist files. Pure derivation — no scraping, no API calls.

Inputs:
  mtg_modern_data/decks/raw/decklists/*_goldfish_decklists.json
  mtg_modern_data/decks/raw/decklists/*_top8_decklists.json

Outputs:
  mtg_modern_data/sources/goldfish/sideboard_frequency_<start>_<end>.json
  mtg_modern_data/sources/goldfish/winrate_<start>_<end>.json

Placement parsing handles:
  "1st" / "6th" / "23rd"  — ordinal rank (no W/L; treated as low-W proxy if event has known size)
  "1 - 1" / "2-0"          — W-L(-D) record. Some use non-breaking spaces (\xa0).
  "-"                       — no data; skip
  "5-0"                     — undefeated; high-W

Usage:
  python3 scripts/aggregate_sideboard_winrate.py
  python3 scripts/aggregate_sideboard_winrate.py --files \\
      mtg_modern_data/decks/raw/decklists/2026-06-03_goldfish_decklists.json \\
      mtg_modern_data/decks/raw/decklists/2026-06-10_top8_decklists.json
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


OUTPUT_DIR = Path("mtg_modern_data/sources/goldfish")


# ─── Placement parser ─────────────────────────────────────────────────────────

RANK_RE = re.compile(r"^(\d+)(?:st|nd|rd|th)$")
WL_RE = re.compile(r"(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?")


def parse_placement(placement: str) -> Optional[Dict[str, int]]:
    """Parse a placement string into a normalized record.

    Returns:
      {"kind": "wl", "wins": int, "losses": int, "draws": int, "games": int}
      {"kind": "rank", "rank": int}
      None if unparseable / missing
    """
    if not placement:
        return None
    s = placement.strip()
    if s in {"-", "", "—"}:
        return None

    # W-L(-D) form
    m = WL_RE.search(s.replace("\xa0", " "))
    if m:
        w, l, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return {"kind": "wl", "wins": w, "losses": l, "draws": d, "games": w + l + d}

    # Ordinal rank
    m = RANK_RE.match(s)
    if m:
        return {"kind": "rank", "rank": int(m.group(1))}

    return None


def winrate_from_record(rec: Dict[str, int]) -> Optional[float]:
    """Compute winrate from a W-L record (ignores draws in numerator by convention)."""
    if rec["kind"] != "wl" or rec["games"] == 0:
        return None
    return rec["wins"] / rec["games"]


# ─── Loaders ─────────────────────────────────────────────────────────────────

def load_decklists(paths: List[Path]) -> List[Dict[str, Any]]:
    out = []
    for p in paths:
        with open(p) as f:
            data = json.load(f)
        decklists = data.get("decklists", data) if isinstance(data, dict) else data
        for d in decklists:
            d["_source_file"] = p.name
            if d.get("legality", {}).get("legal", True):
                out.append(d)
    return out


def canonical_archetype(d: Dict[str, Any]) -> str:
    return (d.get("deck_name_canonical") or d.get("deck_name") or "Unknown").strip()


# ─── Aggregations ────────────────────────────────────────────────────────────

def aggregate_sideboard(decks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-archetype sideboard card frequency.

    For each archetype, count how many decks include each card in their sideboard,
    normalized as ubiquity (fraction of decks with that card). Cards need >= 1 copy.
    """
    by_arch: Dict[str, Counter] = defaultdict(Counter)
    by_arch_decks: Dict[str, int] = defaultdict(int)

    for d in decks:
        arch = canonical_archetype(d)
        sb = d.get("sideboard", []) or []
        cards = set()
        for entry in sb:
            if isinstance(entry, dict):
                name = entry.get("name")
            else:
                name = entry
            if name:
                cards.add(name.strip())
        if not cards:
            continue
        by_arch_decks[arch] += 1
        for c in cards:
            by_arch[arch][c] += 1

    out = {}
    for arch, counter in by_arch.items():
        total = by_arch_decks[arch]
        ranked = [
            {
                "card": card,
                "decks": n,
                "ubiquity": round(n / total, 3) if total else 0,
            }
            for card, n in counter.most_common(15)
            if n / total >= 0.05  # at least 5% ubiquity
        ]
        out[arch] = {
            "deck_count": total,
            "top_sideboard_cards": ranked,
        }
    return out


def aggregate_winrate(decks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-archetype winrate aggregated from W-L records.

    We use ONLY W-L records (not rank-based) for the winrate number, because
    rank-to-winrate is noisy without event-size context. Ranks are reported
    separately as a "top-cut frequency" proxy.
    """
    by_arch_wl: Dict[str, List[Dict[str, int]]] = defaultdict(list)
    by_arch_top8: Dict[str, int] = defaultdict(int)
    by_arch_decks: Dict[str, int] = defaultdict(int)

    for d in decks:
        arch = canonical_archetype(d)
        by_arch_decks[arch] += 1
        rec = parse_placement(d.get("placement", ""))
        if rec is None:
            continue
        if rec["kind"] == "wl":
            by_arch_wl[arch].append(rec)
            # Top 8 finish proxy: if wins >= 4 in a Swiss event (e.g. 4-1, 5-0, 5-1)
            if rec["wins"] >= 4 and rec["losses"] <= 2:
                by_arch_top8[arch] += 1
        elif rec["kind"] == "rank":
            if rec["rank"] <= 8:
                by_arch_top8[arch] += 1

    out = {}
    for arch, records in by_arch_wl.items():
        total_w = sum(r["wins"] for r in records)
        total_l = sum(r["losses"] for r in records)
        total_d = sum(r["draws"] for r in records)
        total_g = total_w + total_l + total_d
        wr = total_w / total_g if total_g else None
        out[arch] = {
            "deck_count": by_arch_decks[arch],
            "wl_record_count": len(records),
            "wins": total_w,
            "losses": total_l,
            "draws": total_d,
            "games": total_g,
            "winrate": round(wr, 3) if wr is not None else None,
            "top_cut_finishes": by_arch_top8.get(arch, 0),
            "top_cut_rate": round(by_arch_top8.get(arch, 0) / by_arch_decks[arch], 3) if by_arch_decks.get(arch) else None,
        }
    return out


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--files", nargs="*", help="Specific decklist JSON files")
    p.add_argument("--all", action="store_true", help="Use all *_decklists.json in raw/decklists/")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    args = p.parse_args()

    if args.files:
        paths = [Path(f) for f in args.files]
    elif args.all or True:
        d = Path("mtg_modern_data/decks/raw/decklists")
        paths = sorted(d.glob("*_decklists.json"))
        # Exclude the goldfish_tournament_index.json (not a decklist file)
        paths = [p for p in paths if "index" not in p.name]

    if not paths:
        raise SystemExit("No input files found.")

    print(f"Loading {len(paths)} files:")
    for p_ in paths:
        print(f"  - {p_}")
    decks = load_decklists(paths)
    print(f"\nTotal legal decks: {len(decks)}")

    sideboard = aggregate_sideboard(decks)
    winrate = aggregate_winrate(decks)

    # Use earliest and latest event_date to derive period; fall back to filenames
    period_starts = []
    period_ends = []
    for p_ in paths:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p_.stem)
        if m:
            period_starts.append(m.group(1))
    period_start = min(period_starts) if period_starts else "unknown"
    period_end = max(period_starts) if period_starts else "unknown"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sb_out = OUTPUT_DIR / f"sideboard_frequency_{period_start}_{period_end}.json"
    wr_out = OUTPUT_DIR / f"winrate_{period_start}_{period_end}.json"

    with open(sb_out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "source": "aggregate from existing decklists",
            "period_start": period_start,
            "period_end": period_end,
            "source_files": [p.name for p in paths],
            "total_decks": len(decks),
            "by_archetype": sideboard,
        }, f, ensure_ascii=False, indent=2)

    with open(wr_out, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "source": "aggregate from existing decklists",
            "period_start": period_start,
            "period_end": period_end,
            "source_files": [p.name for p in paths],
            "total_decks": len(decks),
            "by_archetype": winrate,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {sb_out}")
    print(f"  Archetypes with sideboard data: {len(sideboard)}")
    print(f"\nWrote {wr_out}")
    print(f"  Archetypes with W-L data: {len(winrate)}")

    # Quick top-line summary
    print("\n=== Top 5 archetypes by winrate (min 10 W-L records) ===")
    qualified = [(a, r) for a, r in winrate.items() if r["wl_record_count"] >= 10]
    qualified.sort(key=lambda x: -(x[1]["winrate"] or 0))
    for arch, r in qualified[:5]:
        print(f"  {arch}: {r['winrate']:.1%} ({r['wins']}W-{r['losses']}L-{r['draws']}D, {r['wl_record_count']} records)")


if __name__ == "__main__":
    main()

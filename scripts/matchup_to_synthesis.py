#!/usr/bin/env python3
"""
Read a matchup matrix JSON and merge its insights into an existing synthesis
dict, so the HTML report can include archetype-vs-archetype win rates.

Inputs:
  --matrix mtg_modern_data/sources/topdeck/matchup_matrix_<start>_<end>.json
  --in <synthesis.json>          (optional) existing synthesis to augment
  --out <out.json>                output synthesis with matchup_insights

If --in is omitted, produces a fresh minimal synthesis dict containing only
the matchup data (useful for a matchup-only report).

Usage:
  python3 scripts/matchup_to_synthesis.py \\
      --matrix mtg_modern_data/sources/topdeck/matchup_matrix_2026-05-18_2026-06-10.json \\
      --in /tmp/synthesis_test.json \\
      --out /tmp/synthesis_with_matchup.json
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _pair_winrate(stats: Dict[str, int], archetype: str) -> Dict[str, Any]:
    """Compute win rate for one side of a pair from the symmetric pair stats.

    pair_stats are stored as sorted(a, b) -> {wins1, wins2, draws, games},
    where wins1 corresponds to the alphabetically smaller archetype. The
    caller passes the archetype name; we return games/wins for that side.
    """
    total = stats.get("games", 0)
    if total == 0:
        return {"archetype": archetype, "games": 0, "wins": 0, "losses": 0, "draws": 0, "winrate": None}
    sorted_pair = sorted(stats["_pair"])
    if archetype == sorted_pair[0]:
        wins = stats.get("wins1", 0)
    else:
        wins = stats.get("wins2", 0)
    losses = total - wins - stats.get("draws", 0)
    return {
        "archetype": archetype,
        "games": total,
        "wins": wins,
        "losses": losses,
        "draws": stats.get("draws", 0),
        "winrate": round(wins / total, 3) if total else None,
    }


def build_deck_insights(sb_data: Optional[Dict], wr_data: Optional[Dict], featured_archetypes: List[str]) -> Dict[str, Any]:
    """Build per-archetype insights from sideboard + winrate aggregations.

    Returns a dict like:
      {
        "low_confidence": False,
        "by_archetype": {
          "Boros Energy": {
            "deck_count": 102,
            "winrate": 0.541,
            "top_cut_finishes": 8,
            "top_cut_rate": 0.078,
            "sideboard_top": [{"card": "...", "ubiquity": 0.85}, ...]
          }, ...
        },
        "top_overall_winrate": [...],   # top 10 by winrate, min 10 records
        "featured_archetypes": [...]
      }
    """
    by_arch: Dict[str, Dict[str, Any]] = {}
    sb_by = (sb_data or {}).get("by_archetype", {})
    wr_by = (wr_data or {}).get("by_archetype", {})

    for arch in set(list(sb_by.keys()) + list(wr_by.keys())):
        slot = {}
        if arch in wr_by:
            w = wr_by[arch]
            slot["deck_count"] = w.get("deck_count", 0)
            slot["winrate"] = w.get("winrate")
            slot["wl_record_count"] = w.get("wl_record_count", 0)
            slot["top_cut_finishes"] = w.get("top_cut_finishes", 0)
            slot["top_cut_rate"] = w.get("top_cut_rate")
            slot["record"] = f"{w.get('wins', 0)}W-{w.get('losses', 0)}L"
        if arch in sb_by:
            slot["sideboard_top"] = sb_by[arch].get("top_sideboard_cards", [])[:8]
        by_arch[arch] = slot

    # Top 10 overall by winrate
    qualified = [
        (a, s) for a, s in by_arch.items()
        if s.get("winrate") is not None and s.get("wl_record_count", 0) >= 10
    ]
    qualified.sort(key=lambda x: -(x[1]["winrate"] or 0))
    top_overall = [
        {"archetype": a, "winrate": s["winrate"], "record": s.get("record"),
         "wl_record_count": s.get("wl_record_count"), "deck_count": s.get("deck_count")}
        for a, s in qualified[:10]
    ]

    # Featured
    featured_data = [
        {"archetype": a, **by_arch[a]} for a in featured_archetypes if a in by_arch
    ]

    return {
        "low_confidence": False,  # sideboard/winrate are deterministic aggregations
        "by_archetype": by_arch,
        "top_overall_winrate": top_overall,
        "featured_archetypes": featured_data,
        "total_archetypes": len(by_arch),
    }


def derive_insights(matrix: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a matchup matrix into a list of insights the HTML can render."""
    stats: Dict[str, Dict[str, int]] = matrix.get("matchup_stats", {})
    # Annotate each entry with its sorted pair so winrate can be computed
    annotated = []
    for pair_key, st in stats.items():
        a, b = pair_key.split("|", 1)
        st["_pair"] = (a, b)
        annotated.append({
            "pair": pair_key,
            "a": a, "b": b,
            "games": st.get("games", 0),
            "draws": st.get("draws", 0),
            "winrate_a": round(st.get("wins1", 0) / st["games"], 3) if st.get("games") else None,
            "winrate_b": round(st.get("wins2", 0) / st["games"], 3) if st.get("games") else None,
        })

    # Top pairs by sample size
    top_pairs = sorted(annotated, key=lambda x: -x["games"])[:10]
    # Pairs with extreme winrate (≥ 70% either way) and ≥ 3 games
    polarized = [
        p for p in annotated
        if p["games"] >= 3 and p["winrate_a"] is not None
        and (p["winrate_a"] >= 0.7 or p["winrate_a"] <= 0.3)
    ]
    polarized.sort(key=lambda p: -abs((p["winrate_a"] or 0.5) - 0.5))

    # Aggregate per-archetype total record
    per_arch: Dict[str, Dict[str, int]] = {}
    for p in annotated:
        for arch_key, wins_field in (("a", "winrate_a"), ("b", "winrate_b")):
            arch = p[arch_key]
            wr = p[wins_field]
            if wr is None:
                continue
            slot = per_arch.setdefault(arch, {"games": 0, "wins": 0})
            slot["games"] += p["games"]
            slot["wins"] += round(wr * p["games"])
    archetype_summary = [
        {"archetype": a, **s, "winrate": round(s["wins"] / s["games"], 3) if s["games"] else None}
        for a, s in per_arch.items()
    ]
    archetype_summary.sort(key=lambda x: -x["games"])

    return {
        "low_confidence": matrix.get("low_confidence", True),
        "summary": matrix.get("summary", {}),
        "top_pairs_by_sample": top_pairs,
        "polarized_pairs": polarized[:10],
        "archetype_summary": archetype_summary[:20],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", help="Path to matchup matrix JSON (from extract_matchup_matrix.py)")
    p.add_argument("--sideboard", help="Path to sideboard frequency JSON (from aggregate_sideboard_winrate.py)")
    p.add_argument("--winrate", help="Path to winrate JSON (from aggregate_sideboard_winrate.py)")
    p.add_argument("--in", dest="in_path", help="Existing synthesis JSON to augment")
    p.add_argument("--out", required=True)
    p.add_argument("--top-archetypes", default="Boros Energy,Blink,UW Control,Living End,Eldrazi Tron,Amulet Titan,Grixis Reanimator,UR Prowess",
                   help="Comma-separated archetypes to feature in sideboard/winrate sections")
    args = p.parse_args()

    if not (args.matrix or args.sideboard or args.winrate):
        p.error("At least one of --matrix, --sideboard, --winrate is required.")

    if args.in_path:
        with open(args.in_path) as f:
            data = json.load(f)
    else:
        # Minimal fresh synthesis
        data = {
            "period_start": "", "period_end": "",
            "top_archetypes": [], "new_archetypes": [], "removed_archetypes": [],
            "executive_summary": "", "meta_snapshot_highlights": [],
            "source_recommendations": {"must_add": [], "nice_to_have": [], "skip": []},
        }

    # Matchup data
    if args.matrix:
        matrix = json.load(open(args.matrix))
        insights = derive_insights(matrix)
        data["matchup_insights"] = insights
        data.setdefault("stats", {})
        sm = insights["summary"]
        data["stats"]["matchup_coverage"] = sm.get("classification_coverage", 0.30)
        data["stats"]["matchup_pairs"] = sm.get("archetype_pairs", 0)
        data["stats"]["matchup_classified_matches"] = sm.get("classified_matches", 0)
        data["stats"]["matchup_low_confidence"] = insights["low_confidence"]
        data["stats"]["matchup_players_total"] = sm.get("players", 0)
        data["stats"]["matchup_players_classified"] = sm.get("players_with_decklist", 0)
        # Pull collection scope from the topdeck quality report if present
        try:
            quality_report_path = Path(args.matrix).parent / "topdeck_quality_report.json"
            if quality_report_path.exists():
                qr = json.load(open(quality_report_path))
                payload = qr.get("request_payload", {})
                # Compute window string from payload (prefer "last N days" or start/end as dates)
                if "last" in payload:
                    window_str = f"last {payload['last']} days"
                elif "start" in payload and "end" in payload:
                    from datetime import datetime, timezone
                    start_dt = datetime.fromtimestamp(payload["start"], tz=timezone.utc).date()
                    end_dt = datetime.fromtimestamp(payload["end"], tz=timezone.utc).date()
                    window_str = f"{start_dt} ~ {end_dt}"
                else:
                    window_str = "unknown"
                # Pre-format threshold map (gate keys to threshold keys)
                gate_results = qr.get("quality_gate_results", {})
                gate_thresholds = qr.get("quality_gate", {})
                threshold_map = {
                    "completed_events": gate_thresholds.get("min_completed_events", "?"),
                    "classified_match_count": gate_thresholds.get("min_classified_matches", "?"),
                    "classification_coverage": gate_thresholds.get("min_classification_coverage", "?"),
                    "top_pair_sample_count": gate_thresholds.get("min_top_pair_sample_count", "?"),
                }
                data["collection_scope"] = {
                    "source": "Topdeck.gg",
                    "format": payload.get("format", "Modern"),
                    "window": window_str,
                    "participant_min": payload.get("participantMin", "?"),
                    "rounds_requested": payload.get("rounds", False),
                    "tables_columns": payload.get("tables", []),
                    "players_columns": payload.get("players", []),
                    "quality_gate_thresholds": threshold_map,
                    "quality_gate_results": gate_results,
                    "passed": qr.get("passed", False),
                    "low_confidence": insights["low_confidence"],
                    "fetched_at": qr.get("generated_at", ""),
                }
        except Exception as e:
            print(f"warn: could not load collection scope: {e}")
        if not data["period_start"] and matrix.get("period_start"):
            data["period_start"] = matrix["period_start"]
        if not data["period_end"] and matrix.get("period_end"):
            data["period_end"] = matrix["period_end"]

    # Sideboard + winrate data
    if args.sideboard or args.winrate:
        featured = [a.strip() for a in args.top_archetypes.split(",") if a.strip()]
        sb_data = json.load(open(args.sideboard)) if args.sideboard else None
        wr_data = json.load(open(args.winrate)) if args.winrate else None
        data["deck_insights"] = build_deck_insights(sb_data, wr_data, featured)
        if sb_data and not data.get("period_start"):
            data["period_start"] = sb_data.get("period_start", "")
        if sb_data and not data.get("period_end"):
            data["period_end"] = sb_data.get("period_end", "")
        # Update top archetypes by real winrate if we have winrate data
        if wr_data and featured:
            wr = wr_data.get("by_archetype", {})
            ranked = sorted(
                [(a, wr[a]) for a in featured if a in wr and wr[a].get("winrate") is not None],
                key=lambda x: -(x[1]["winrate"] or 0)
            )
            if ranked:
                # Merge into existing top_archetypes by name, augmenting with winrate
                existing = {t.get("archetype"): t for t in data.get("top_archetypes", [])}
                for arch, w in ranked:
                    if arch in existing:
                        existing[arch]["winrate_aggregate"] = w["winrate"]
                data["top_archetypes"] = list(existing.values())

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out}")
    print(f"  Top pairs (by games): {len(insights['top_pairs_by_sample'])}")
    print(f"  Polarized pairs (≥3 games, ≥70% WR): {len(insights['polarized_pairs'])}")
    print(f"  Archetypes with aggregate WR: {len(insights['archetype_summary'])}")
    if insights["low_confidence"]:
        print("  ⚠ low_confidence=true — quality gate failed; insights are exploratory.")


if __name__ == "__main__":
    main()

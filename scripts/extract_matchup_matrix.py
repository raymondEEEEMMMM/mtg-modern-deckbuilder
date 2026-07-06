#!/usr/bin/env python3
"""
TopDeck.gg matchup matrix extractor (production wrapper over topdeck_poc.py).

Differences from the PoC:
  - Default confidence 0.35 (was 0.45) to improve classification coverage
  - --max-events cap (default 30) to control API call size
  - --always-emit-matrix: writes matchup matrix even when quality gate fails
  - Period-based output filename: matchup_matrix_<start>_<end>.json
  - --from-fixture FILE: skip API, analyze a saved raw payload (for tests)

Outputs:
  mtg_modern_data/sources/topdeck/matchup_matrix_<start>_<end>.json
  mtg_modern_data/sources/topdeck/topdeck_quality_report.json (overwritten)

Usage:
  TOPDECK_API_KEY=... python3 scripts/extract_matchup_matrix.py
  TOPDECK_API_KEY=... python3 scripts/extract_matchup_matrix.py --max-events 50
  python3 scripts/extract_matchup_matrix.py --from-fixture \\
      mtg_modern_data/sources/topdeck/raw/topdeck_modern_2026-05-18.json

Note on --from-fixture:
  --from-fixture skips the API call and analyzes a saved raw payload.
  In this mode, --start/--end are IGNORED — the script uses the fixture's
  own time window (typically "last N days" relative to when the payload
  was captured), and the output filename reflects that fixture window,
  not the --start/--end you passed. Pass --start/--end only for live API
  runs; for fixture replays, trust the filename.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import topdeck_poc  # noqa: E402

BASE = topdeck_poc.BASE
OUTPUT_DIR = topdeck_poc.OUTPUT_DIR
RAW_DIR = topdeck_poc.RAW_DIR
META_PATH = topdeck_poc.META_PATH
REPORT_PATH = topdeck_poc.REPORT_PATH


def parse_args():
    p = argparse.ArgumentParser(description="Extract TopDeck matchup matrix.")
    p.add_argument("--start", help="Period start (YYYY-MM-DD). Default: meta.json latest B&R")
    p.add_argument("--end", help="Period end (YYYY-MM-DD). Default: today")
    p.add_argument("--max-events", type=int, default=30,
                   help="Cap number of tournaments (default 30)")
    p.add_argument("--participant-min", type=int, default=8)
    p.add_argument("--confidence", type=float, default=0.35,
                   help="Min classification confidence (default 0.35, was 0.45 in PoC)")
    p.add_argument("--last", type=int, default=None,
                   help="Days back from today (overrides --start/--end)")
    p.add_argument("--always-emit-matrix", action="store_true", default=True,
                   help="Write matrix even when quality gate fails (default: True)")
    p.add_argument("--from-fixture",
                   help="Path to a saved topdeck raw JSON; skip API call entirely")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def resolve_period(args) -> tuple:
    if args.start and args.end:
        return args.start, args.end
    meta = topdeck_poc.load_json(META_PATH)
    start = args.start or meta["changes_history"][-1]["effective_date"]
    end = args.end or datetime.now(timezone.utc).date().isoformat()
    return start, end


def build_payload(args, start, end) -> dict:
    payload = {
        "game": "Magic: The Gathering",
        "format": "Modern",
        "participantMin": args.participant_min,
        "columns": ["name", "id", "decklist", "wins", "draws", "losses"],
        "rounds": True,
        "tables": ["table", "players", "winner", "status"],
        "players": ["name", "id", "decklist"],
    }
    if args.last:
        payload["last"] = args.last
    else:
        payload["start"] = topdeck_poc.unix_seconds(start)
        payload["end"] = topdeck_poc.unix_seconds(end)
    return payload


def matrix_path(start, end) -> Path:
    return OUTPUT_DIR / f"matchup_matrix_{start}_{end}.json"


def derive_matrix_window(fix: dict) -> tuple:
    """In --from-fixture mode, derive the matrix's (start, end) labels from
    the fixture's payload. Falls back to meta.json period if payload lacks
    start/end timestamps.
    """
    payload = fix.get("payload", {})
    if "last" in payload:
        from datetime import datetime, timedelta
        end_dt = datetime.now().date()  # local time, not UTC, to match report date
        start_dt = end_dt - timedelta(days=int(payload["last"]))
        return start_dt.isoformat(), end_dt.isoformat()
    if "start" in payload and "end" in payload:
        from datetime import datetime, timezone
        start = datetime.fromtimestamp(int(payload["start"]), tz=timezone.utc).date().isoformat()
        end = datetime.fromtimestamp(int(payload["end"]), tz=timezone.utc).date().isoformat()
        return start, end
    return ("unknown", "unknown")


def write_matrix(out_path: Path, tournaments, analysis, trial_stats, payload, gate_passed):
    matrix = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "TopDeck.gg API",
        "attribution_required": "Data provided by TopDeck.gg: https://topdeck.gg",
        "period_start": payload.get("start_date") or "",
        "period_end": payload.get("end_date") or "",
        "low_confidence": not gate_passed,
        "quality_gate_failed_reasons": _gate_fail_reasons(tournaments, analysis, trial_stats),
        "summary": {
            "events": len(tournaments),
            "players": analysis["player_count"],
            "players_with_decklist": analysis["players_with_decklist"],
            "decklist_coverage": analysis["decklist_coverage"],
            "classification_coverage": analysis["classification_coverage"],
            "classified_matches": len(analysis["match_records"]),
            "archetype_pairs": len(trial_stats),
        },
        "matchup_stats": trial_stats,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, indent=2)
    return matrix


def _gate_fail_reasons(tournaments, analysis, trial_stats):
    reasons = []
    qg = topdeck_poc.QUALITY_GATE
    if len(tournaments) < qg["min_completed_events"]:
        reasons.append(f"events {len(tournaments)} < {qg['min_completed_events']}")
    if len(analysis["match_records"]) < qg["min_classified_matches"]:
        reasons.append(f"matches {len(analysis['match_records'])} < {qg['min_classified_matches']}")
    if analysis["classification_coverage"] < qg["min_classification_coverage"]:
        reasons.append(f"coverage {analysis['classification_coverage']:.2f} < {qg['min_classification_coverage']}")
    return reasons


def main():
    args = parse_args()
    # If from-fixture and it has a payload with start/end/last, use it as the matrix window
    fixture_for_window = None
    if args.from_fixture:
        try:
            fixture_for_window = json.load(open(args.from_fixture))
        except Exception:
            fixture_for_window = None

    if fixture_for_window is not None and fixture_for_window.get("payload"):
        win_start, win_end = derive_matrix_window(fixture_for_window)
        start, end = win_start, win_end
        payload = fixture_for_window["payload"]
    else:
        start, end = resolve_period(args)
        payload = build_payload(args, start, end)
    out = matrix_path(start, end)
    payload_path = OUTPUT_DIR / "topdeck_request_payload.json"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if args.dry_run:
        print(f"Dry run. Would request: {payload}")
        print(f"Would write: {out}")
        return

    # Get tournaments: either from fixture or via API
    if args.from_fixture:
        fix = json.load(open(args.from_fixture))
        tournaments = fix["tournaments"]
        # Inherit the fixture's payload as the source of truth for the API call params
        fixture_payload = fix.get("payload", {})
        if fixture_payload:
            payload = fixture_payload
            print(f"Loaded {len(tournaments)} events from fixture {args.from_fixture}")
            print(f"  using fixture payload: {payload}")
        else:
            print(f"Loaded {len(tournaments)} events from fixture {args.from_fixture} (no payload metadata)")
    else:
        api_key = os.environ.get("TOPDECK_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "TOPDECK_API_KEY not set. Either export it, or pass "
                "--from-fixture PATH to analyze a saved raw payload."
            )
        tournaments = topdeck_poc.request_topdeck(api_key, payload)
        if not isinstance(tournaments, list):
            raise SystemExit(f"Unexpected TopDeck response: {type(tournaments)}")
        # Cap to --max-events
        if len(tournaments) > args.max_events:
            print(f"Capping {len(tournaments)} events to --max-events={args.max_events}")
            tournaments = tournaments[:args.max_events]
        # Save raw for replay
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_DIR / f"topdeck_modern_{start}.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump({
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "period_start": start, "period_end": end,
                "payload": payload, "tournaments": tournaments,
            }, f, ensure_ascii=False, indent=2)
        print(f"Saved raw to {raw_path}")

    profiles = topdeck_poc.build_archetype_profiles()
    analysis = topdeck_poc.analyze_tournaments(tournaments, profiles, args.confidence)
    trial_stats = topdeck_poc.build_trial_matrix(analysis["match_records"])
    report = topdeck_poc.quality_report(tournaments, analysis, trial_stats, payload)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    gate_passed = report["passed"]
    if gate_passed or args.always_emit_matrix:
        matrix = write_matrix(out, tournaments, analysis, trial_stats, payload, gate_passed)
        print(f"\nMatrix written: {out}")
        print(json.dumps(matrix["summary"], ensure_ascii=False, indent=2))
        if not gate_passed:
            print(f"⚠ Quality gate FAILED — reasons: {matrix['quality_gate_failed_reasons']}")
            print("  Matrix emitted with low_confidence=true; use for exploratory analysis only.")
    else:
        print("Quality gate failed and --always-emit-matrix is False; no matrix written.")

    print(f"\nReport: {REPORT_PATH}")
    print(f"Passed quality gate: {gate_passed}")


if __name__ == "__main__":
    main()

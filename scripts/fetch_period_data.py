#!/usr/bin/env python3
"""Run MTGTop8 and MTGGoldfish decklists scrapers for a single ban period.

Usage:
  python3 scripts/fetch_period_data.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--dry-run]

Default period: start = latest B&R effective_date from ban_list/meta.json,
end = today. Both are passed through to the underlying scrapers, which now
accept --start / --end flags (see scrape_decklists_top8.py and
scrape_goldfish_two_phase.py).
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from period_utils import resolve_period_args  # noqa: E402

DEFAULT_META = ROOT / "mtg_modern_data" / "ban_list" / "meta.json"
DEFAULT_FALLBACK_START = "2026-05-18"


def parse_args(argv: Sequence[str], fallback: str = DEFAULT_FALLBACK_START) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch MTGTop8 + MTGGoldfish decklists for a period.")
    p.add_argument("--start", help="Period start (YYYY-MM-DD). Default: meta.json latest B&R date.")
    p.add_argument("--end", help="Period end (YYYY-MM-DD). Default: today.")
    p.add_argument("--meta", default=str(DEFAULT_META), help="Path to ban_list/meta.json")
    p.add_argument("--max-events", type=int, default=999, help="Cap for Top8 event count")
    p.add_argument("--max-tournaments", type=int, default=999, help="Cap for Goldfish tournament count")
    p.add_argument("--no-skip-top8-overlap", action="store_true",
                   help="Pass --skip-top8-overlap to Goldfish (default: skip Top8 overlap)")
    p.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = p.parse_args(list(argv))

    try:
        period = resolve_period_args(
            start=args.start, end=args.end,
            meta_path=Path(args.meta), fallback=fallback,
        )
    except ValueError as e:
        # Surface period-resolution errors as a clean CLI error (SystemExit via parser.error).
        p.error(str(e))
    args.start, args.end = period.start, period.end
    return args


def build_commands(start: str, end: str,
                   max_events: int = 999, max_tournaments: int = 999,
                   skip_top8_overlap: bool = True) -> list[list[str]]:
    top8 = [
        sys.executable, str(ROOT / "scrape_decklists_top8.py"),
        "--max-events", str(max_events),
        "--start", start, "--end", end,
    ]
    goldfish = [
        sys.executable, str(ROOT / "scrape_goldfish_two_phase.py"),
        "--max-tournaments", str(max_tournaments),
        "--start", start, "--end", end,
    ]
    if skip_top8_overlap:
        goldfish.append("--skip-top8-overlap")
    return [top8, goldfish]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    print(f"=== Period Data Fetch ===")
    print(f"Period: {args.start} ~ {args.end}")
    print(f"Meta:   {args.meta}")

    commands = build_commands(
        start=args.start, end=args.end,
        max_events=args.max_events, max_tournaments=args.max_tournaments,
        skip_top8_overlap=not args.no_skip_top8_overlap,
    )

    labels = ["MTGTop8", "MTGGoldfish"]
    for label, cmd in zip(labels, commands):
        print(f"\n--- Running {label} ---")
        print("  $ " + " ".join(cmd))
        if args.dry_run:
            continue
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n{label} failed (rc={result.returncode}); aborting pipeline.")
            return result.returncode

    print(f"\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

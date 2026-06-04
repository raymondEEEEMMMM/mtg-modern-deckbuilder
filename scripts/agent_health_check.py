"""Deterministic health check for the MTG Modern Meta Agent.

Reads the current banlist period and checks freshness of the 4 key data
products. Emits a structured JSON report on stdout.

Spec: docs/superpowers/specs/2026-06-04-mtg-agent-init-design.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from scripts.period_utils import load_period_start_from_meta

REPO_ROOT = Path(__file__).resolve().parent.parent
META_PATH = REPO_ROOT / "mtg_modern_data" / "ban_list" / "meta.json"

# (product_name, relative path, command(s) to regenerate)
PRODUCTS: list[tuple[str, str, list[str]]] = [
    (
        "fused_archetypes",
        "mtg_modern_data/decks/processed/fused_archetypes.json",
        [
            "python3 scrape_decklists_top8.py --max-events 999",
            "python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap",
        ],
    ),
    (
        "top_decks",
        "mtg_modern_data/decks/top_n/top_decks.json",
        ["python3 evaluate_deck_strength.py --top 15"],
    ),
    (
        "card_impact",
        "mtg_modern_data/cards/card_impact.json",
        ["python3 scripts/build_card_impact.py"],
    ),
    (
        "meta_current",
        "mtg_modern_data/meta/current.json",
        ["python3 compose_meta.py"],
    ),
]

STALE_AGE_DAYS = 7


def build_period_info(meta_path: Path, today: Optional[date] = None) -> dict:
    """Derive current banlist period info from meta.json.

    Raises ValueError if meta.json is unreadable or has no changes_history.
    """
    start = load_period_start_from_meta(meta_path, fallback="")
    if not start:
        raise ValueError(f"could not determine period start from {meta_path}")
    today = today or date.today()
    start_date = date.fromisoformat(start)
    return {
        "start": start,
        "today": today.isoformat(),
        "days_since_start": (today - start_date).days,
    }


def check_product(
    name: str,
    path: Path,
    period_start: date,
    today: Optional[date] = None,
    stale_age_days: int = STALE_AGE_DAYS,
) -> dict:
    """Inspect a single data product and return its freshness record."""
    today = today or date.today()
    if not path.exists():
        return {
            "name": name,
            "path": str(path),
            "exists": False,
            "mtime": None,
            "days_old": None,
            "stale": True,
            "reason": "missing",
        }
    mtime_ts = path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime_ts)
    mtime_date = mtime_dt.date()
    days_old = (today - mtime_date).days
    if mtime_date < period_start:
        stale, reason = True, "predates_current_period"
    elif days_old > stale_age_days:
        stale, reason = True, "older_than_7d"
    else:
        stale, reason = False, None
    return {
        "name": name,
        "path": str(path),
        "exists": True,
        "mtime": mtime_dt.isoformat(timespec="seconds"),
        "days_old": days_old,
        "stale": stale,
        "reason": reason,
    }


def build_recommendations(products: list[dict]) -> list[str]:
    """Map stale products to deduplicated, pipeline-ordered commands."""
    commands_by_product = {name: cmds for name, _, cmds in PRODUCTS}
    seen: set[str] = set()
    out: list[str] = []
    # Iterate in PRODUCTS order so output respects pipeline order
    for name, _, _ in PRODUCTS:
        product = next((p for p in products if p["name"] == name), None)
        if product is None or not product["stale"]:
            continue
        for cmd in commands_by_product[name]:
            if cmd not in seen:
                seen.add(cmd)
                out.append(cmd)
    return out


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())

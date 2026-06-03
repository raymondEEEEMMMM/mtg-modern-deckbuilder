"""Period detection and ISO date parsing for ban-window-bound scrapers."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class PeriodArgs:
    start: str  # YYYY-MM-DD
    end: str    # YYYY-MM-DD


def load_period_start_from_meta(meta_path: Path, fallback: str = "2026-05-18") -> str:
    """Read ban_list/meta.json and return the latest B&R effective_date."""
    if not meta_path.exists():
        return fallback
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        return fallback
    history = meta.get("changes_history") or []
    if not history:
        return fallback
    return history[-1].get("effective_date", fallback) or fallback


def parse_iso_date(value: str) -> str:
    """Validate an ISO YYYY-MM-DD string. Return it on success; raise on failure."""
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        raise ValueError(f"expected ISO date YYYY-MM-DD, got {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid calendar date {value!r}: {e}") from e
    return value


def resolve_period_args(
    start: Optional[str],
    end: Optional[str],
    meta_path: Path,
    fallback: str = "2026-05-18",
    today: Optional[date] = None,
) -> PeriodArgs:
    """Resolve a (start, end) pair from CLI args, defaulting start to meta and end to today."""
    resolved_start = parse_iso_date(start) if start else load_period_start_from_meta(meta_path, fallback)
    if end:
        resolved_end = parse_iso_date(end)
    else:
        # `date.today()` may be mocked to return a datetime in tests; normalize to date.
        resolved_today = today or date.today()
        if isinstance(resolved_today, datetime):
            resolved_today = resolved_today.date()
        resolved_end = resolved_today.isoformat()
    if resolved_start > resolved_end:
        raise ValueError(
            f"start must be <= end (got start={resolved_start}, end={resolved_end})"
        )
    return PeriodArgs(start=resolved_start, end=resolved_end)

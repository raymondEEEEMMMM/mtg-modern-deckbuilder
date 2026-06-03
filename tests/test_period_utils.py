import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.period_utils import (
    load_period_start_from_meta,
    parse_iso_date,
    resolve_period_args,
    PeriodArgs,
)


# ─── load_period_start_from_meta ──────────────────────────────────────────────

def test_load_period_start_uses_latest_effective_date(tmp_path: Path):
    meta = {
        "changes_history": [
            {"effective_date": "2024-01-01"},
            {"effective_date": "2025-08-26"},
            {"effective_date": "2026-05-18"},
        ]
    }
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(meta))
    assert load_period_start_from_meta(path) == "2026-05-18"


def test_load_period_start_falls_back_when_file_missing(tmp_path: Path):
    assert load_period_start_from_meta(tmp_path / "missing.json", fallback="2026-05-18") == "2026-05-18"


def test_load_period_start_falls_back_when_history_empty(tmp_path: Path):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"changes_history": []}))
    assert load_period_start_from_meta(path, fallback="2026-05-18") == "2026-05-18"


# ─── parse_iso_date ───────────────────────────────────────────────────────────

def test_parse_iso_date_valid():
    assert parse_iso_date("2026-05-18") == "2026-05-18"


@pytest.mark.parametrize("bad", ["2026/05/18", "18-05-2026", "2026-5-18", "not-a-date", ""])
def test_parse_iso_date_rejects_non_iso(bad):
    with pytest.raises(ValueError):
        parse_iso_date(bad)


# ─── resolve_period_args ──────────────────────────────────────────────────────

def test_resolve_period_uses_meta_start_and_today_when_only_end_given(tmp_path: Path):
    meta = {"changes_history": [{"effective_date": "2026-05-18"}]}
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(meta))

    with patch("scripts.period_utils.date") as mock_date:
        mock_date.today.return_value = datetime(2026, 6, 3)
        result = resolve_period_args(
            start=None, end=None, meta_path=path, fallback="2026-05-18"
        )
    assert result == PeriodArgs(start="2026-05-18", end="2026-06-03")


def test_resolve_period_explicit_start_and_end():
    result = resolve_period_args(
        start="2026-01-01", end="2026-03-01", meta_path=Path("/nonexistent")
    )
    assert result.start == "2026-01-01"
    assert result.end == "2026-03-01"


def test_resolve_period_rejects_inverted_range():
    with pytest.raises(ValueError, match="start must be"):
        resolve_period_args(
            start="2026-05-01", end="2026-04-01", meta_path=Path("/nonexistent")
        )


def test_resolve_period_rejects_malformed_start():
    with pytest.raises(ValueError):
        resolve_period_args(
            start="not-a-date", end="2026-05-01", meta_path=Path("/nonexistent")
        )

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.agent_health_check import build_period_info, check_product


def _write_meta(tmp_path: Path, effective_dates: list[str]) -> Path:
    meta = {
        "changes_history": [
            {"effective_date": d} for d in effective_dates
        ]
    }
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(meta))
    return path


def test_build_period_info_returns_latest_effective_date_and_days(tmp_path: Path):
    meta = _write_meta(tmp_path, ["2024-01-01", "2026-05-18"])
    info = build_period_info(meta, today=date(2026, 6, 4))
    assert info == {
        "start": "2026-05-18",
        "today": "2026-06-04",
        "days_since_start": 17,
    }


def test_build_period_info_raises_when_meta_missing(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError, match="could not determine period start"):
        build_period_info(missing, today=date(2026, 6, 4))


def test_build_period_info_raises_when_history_empty(tmp_path: Path):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"changes_history": []}))
    with pytest.raises(ValueError, match="could not determine period start"):
        build_period_info(path, today=date(2026, 6, 4))


def test_check_product_marks_missing_file_as_stale(tmp_path: Path):
    result = check_product(
        name="card_impact",
        path=tmp_path / "absent.json",
        period_start=date(2026, 5, 18),
        today=date(2026, 6, 4),
    )
    assert result["name"] == "card_impact"
    assert result["exists"] is False
    assert result["mtime"] is None
    assert result["days_old"] is None
    assert result["stale"] is True
    assert result["reason"] == "missing"


import os


def _touch(path: Path, when: date) -> None:
    path.write_text("{}")
    ts = datetime.combine(when, datetime.min.time()).timestamp()
    os.utime(path, (ts, ts))


def test_check_product_marks_old_file_as_predates_period(tmp_path: Path):
    p = tmp_path / "card_impact.json"
    _touch(p, date(2026, 5, 10))  # before period_start
    result = check_product(
        name="card_impact",
        path=p,
        period_start=date(2026, 5, 18),
        today=date(2026, 6, 4),
    )
    assert result["exists"] is True
    assert result["stale"] is True
    assert result["reason"] == "predates_current_period"

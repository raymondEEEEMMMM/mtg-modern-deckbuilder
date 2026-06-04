import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.agent_health_check import build_period_info, build_recommendations, check_product


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


def test_check_product_marks_in_period_but_old_as_older_than_7d(tmp_path: Path):
    p = tmp_path / "top_decks.json"
    _touch(p, date(2026, 5, 25))  # within period but 10 days before today
    result = check_product(
        name="top_decks",
        path=p,
        period_start=date(2026, 5, 18),
        today=date(2026, 6, 4),
    )
    assert result["stale"] is True
    assert result["reason"] == "older_than_7d"
    assert result["days_old"] == 10


def test_check_product_marks_fresh_file_as_not_stale(tmp_path: Path):
    p = tmp_path / "fused.json"
    _touch(p, date(2026, 6, 3))
    result = check_product(
        name="fused_archetypes",
        path=p,
        period_start=date(2026, 5, 18),
        today=date(2026, 6, 4),
    )
    assert result["stale"] is False
    assert result["reason"] is None
    assert result["days_old"] == 1


def test_build_recommendations_single_stale_product():
    products = [
        {"name": "fused_archetypes", "stale": False},
        {"name": "top_decks", "stale": False},
        {"name": "card_impact", "stale": True},
        {"name": "meta_current", "stale": False},
    ]
    assert build_recommendations(products) == [
        "python3 scripts/build_card_impact.py",
    ]


def test_build_recommendations_dedups_and_orders_by_pipeline():
    products = [
        {"name": "fused_archetypes", "stale": True},
        {"name": "top_decks", "stale": True},
        {"name": "card_impact", "stale": True},
        {"name": "meta_current", "stale": True},
    ]
    assert build_recommendations(products) == [
        "python3 scrape_decklists_top8.py --max-events 999",
        "python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap",
        "python3 evaluate_deck_strength.py --top 15",
        "python3 scripts/build_card_impact.py",
        "python3 compose_meta.py",
    ]


def test_build_recommendations_empty_when_nothing_stale():
    products = [
        {"name": "fused_archetypes", "stale": False},
        {"name": "top_decks", "stale": False},
        {"name": "card_impact", "stale": False},
        {"name": "meta_current", "stale": False},
    ]
    assert build_recommendations(products) == []

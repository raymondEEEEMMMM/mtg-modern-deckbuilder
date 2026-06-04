import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.agent_health_check import build_period_info, build_recommendations, check_product, run_health_check


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


def test_run_health_check_assembles_full_report(tmp_path: Path):
    # meta.json
    meta_path = _write_meta(tmp_path, ["2026-05-18"])
    # data products
    data_root = tmp_path / "mtg_modern_data"
    fused = data_root / "decks" / "processed" / "fused_archetypes.json"
    top = data_root / "decks" / "top_n" / "top_decks.json"
    card = data_root / "cards" / "card_impact.json"
    meta_current = data_root / "meta" / "current.json"
    for p in [fused, top, card, meta_current]:
        p.parent.mkdir(parents=True, exist_ok=True)
    _touch(fused, date(2026, 6, 3))         # fresh
    _touch(top, date(2026, 6, 3))           # fresh
    _touch(card, date(2026, 5, 10))         # predates period
    _touch(meta_current, date(2026, 6, 3))  # fresh

    report = run_health_check(
        meta_path=meta_path,
        data_root=data_root,
        today=date(2026, 6, 4),
    )

    assert report["period"] == {
        "start": "2026-05-18",
        "today": "2026-06-04",
        "days_since_start": 17,
    }
    assert {p["name"] for p in report["products"]} == {
        "fused_archetypes", "top_decks", "card_impact", "meta_current",
    }
    assert report["stale_products"] == ["card_impact"]
    assert report["recommended_next_steps"] == ["python3 scripts/build_card_impact.py"]
    assert "generated_at" in report


def test_main_writes_json_to_stdout_when_meta_valid(tmp_path: Path, capsys):
    from scripts.agent_health_check import main as cli_main

    meta_path = _write_meta(tmp_path, ["2026-05-18"])
    data_root = tmp_path / "mtg_modern_data"
    (data_root / "decks" / "processed").mkdir(parents=True)
    (data_root / "decks" / "top_n").mkdir(parents=True)
    (data_root / "cards").mkdir(parents=True)
    (data_root / "meta").mkdir(parents=True)

    rc = cli_main([
        "--meta", str(meta_path),
        "--data-root", str(data_root),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "period" in payload
    assert payload["period"]["start"] == "2026-05-18"


def test_main_exits_2_when_meta_missing(tmp_path: Path, capsys):
    from scripts.agent_health_check import main as cli_main

    rc = cli_main([
        "--meta", str(tmp_path / "absent.json"),
        "--data-root", str(tmp_path / "data"),
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "could not determine period start" in captured.err

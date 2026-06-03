import sys
from pathlib import Path
from unittest.mock import patch, call

import pytest

from scripts import fetch_period_data


def test_resolve_args_from_meta_default(tmp_path: Path):
    import json
    (tmp_path / "meta.json").write_text(json.dumps({
        "changes_history": [{"effective_date": "2026-05-18"}]
    }))
    args = fetch_period_data.parse_args(
        ["--meta", str(tmp_path / "meta.json")], fallback="2026-05-18"
    )
    assert args.start == "2026-05-18"
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", args.end)  # resolved to today


def test_resolve_args_explicit_range(tmp_path: Path):
    args = fetch_period_data.parse_args(
        ["--start", "2026-01-01", "--end", "2026-03-01",
         "--meta", str(tmp_path / "missing.json")],
        fallback="2026-05-18",
    )
    assert args.start == "2026-01-01"
    assert args.end == "2026-03-01"


def test_resolve_args_rejects_inverted():
    with pytest.raises(SystemExit):
        fetch_period_data.parse_args(
            ["--start", "2026-05-01", "--end", "2026-04-01",
             "--meta", "/nonexistent"],
            fallback="2026-05-18",
        )


def test_build_commands_top8_then_goldfish():
    """The Top8 scraper must be invoked first; Goldfish second with --skip-top8-overlap."""
    cmds = fetch_period_data.build_commands(
        start="2026-05-18", end="2026-06-03"
    )
    assert len(cmds) == 2
    top8, goldfish = cmds
    # top8[0] is sys.executable; the script path is top8[1].
    assert "scrape_decklists_top8.py" in top8[1]
    assert "--start" in top8 and "2026-05-18" in top8
    assert "--end" in top8 and "2026-06-03" in top8
    assert "scrape_goldfish_two_phase.py" in goldfish[1]
    assert "--skip-top8-overlap" in goldfish
    assert "--start" in goldfish and "2026-05-18" in goldfish
    assert "--end" in goldfish and "2026-06-03" in goldfish


@patch("scripts.fetch_period_data.subprocess.run")
def test_main_runs_both_scrapers(mock_run, tmp_path, capsys):
    (tmp_path / "meta.json").write_text('{"changes_history": [{"effective_date": "2026-05-18"}]}')
    mock_run.return_value.returncode = 0

    rc = fetch_period_data.main([
        "--meta", str(tmp_path / "meta.json"),
        "--start", "2026-05-18", "--end", "2026-06-03",
        # No --dry-run: the mock prevents real execution. We want subprocess.run called
        # so we can assert call_count and verify both scrapers were invoked.
    ])
    assert rc == 0
    assert mock_run.call_count == 2
    out = capsys.readouterr().out
    assert "MTGTop8" in out and "MTGGoldfish" in out


@patch("scripts.fetch_period_data.subprocess.run")
def test_main_aborts_if_top8_fails(mock_run, tmp_path, capsys):
    (tmp_path / "meta.json").write_text('{"changes_history": [{"effective_date": "2026-05-18"}]}')
    mock_run.side_effect = [
        __import__("subprocess").CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"),
        __import__("subprocess").CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]
    rc = fetch_period_data.main([
        "--meta", str(tmp_path / "meta.json"),
        "--start", "2026-05-18", "--end", "2026-06-03",
        # No --dry-run: the mock prevents real execution and lets us verify Goldfish is skipped.
    ])
    assert rc == 1
    # Goldfish must not run if Top8 failed
    assert mock_run.call_count == 1
    # The user must see an error message, not just a silent non-zero exit code.
    out = capsys.readouterr().out
    assert "failed" in out or "aborting" in out

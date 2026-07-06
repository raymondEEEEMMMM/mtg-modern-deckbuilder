# Period-Bounded Data Fetch (MTGTop8 + MTGGoldfish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MTGTop8 and MTGGoldfish decklists fetchable for an explicit period (`--start` / `--end`), expose a single orchestrator that runs both for the current period, and stamp every output with `period_start` / `period_end` so downstream consumers can reason about the data window.

**Architecture:** A new `scripts/period_utils.py` owns period detection (`changes_history[-1].effective_date` from `ban_list/meta.json`) and ISO-date parsing/validation. Both decklist scrapers (`scrape_decklists_top8.py`, `scrape_goldfish_two_phase.py`) consume it via new `--start` / `--end` CLI flags (parsed with the existing `sys.argv` style) and stamp `period_start` + `period_end` into their output JSON. A new `scripts/fetch_period_data.py` runs both scrapers in sequence for one period and prints a summary. Both skill `SKILL.md` files are updated to document the new flags and the orchestrator.

**Tech Stack:** Python 3, pytest 7.4, existing playwright-based scrapers, no new dependencies.

---

## Context

Today the two decklist scrapers each load `ban_list/meta.json` at import time and read `changes_history[-1].effective_date` as `PERIOD_START`. The end of the period is implicit ("today" — `datetime.now()`). Re-running the pipeline for a non-current period (e.g., rebuilding a previous ban window, or for a backfill when a new B&R drops mid-week) is impossible without editing source. Both scrapers also drift independently: the same fallback constant `"2026-05-18"` and the same import-time `META_FILE` resolution live in two files.

The "current period" data flow today:
- `scrape_decklists_top8.py` → `decks/raw/decklists/YYYY-MM-DD_top8_decklists.json` (stamps `period_start` only)
- `scrape_goldfish_two_phase.py` → `decks/raw/decklists/YYYY-MM-DD_goldfish_decklists.json` (stamps `period_start` only)
- Outputs feed `evaluate_deck_strength.py` → `compose_meta.py`

What this plan adds:
- A single source of truth for period parsing (`scripts/period_utils.py`).
- `--start` and `--end` flags on both scrapers; end defaults to today if omitted.
- `period_end` written to every output JSON alongside `period_start`.
- A new `scripts/fetch_period_data.py` orchestrator that runs both scrapers for one period and prints a summary.
- Tests for the new utility, the new flag plumbing, and the orchestrator's period-resolution behavior.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `scripts/period_utils.py` | Create | Pure functions: `load_period_start_from_meta()`, `parse_iso_date()`, `resolve_period_args()` |
| `tests/test_period_utils.py` | Create | Tests for date parsing, period resolution, default end=today |
| `scrape_decklists_top8.py` | Modify | Replace inline `PERIOD_START` block with `period_utils` import; add `--start` / `--end` flags; stamp `period_end` in output |
| `scrape_goldfish_two_phase.py` | Modify | Same: replace inline `PERIOD_START`, add `--start` / `--end`, stamp `period_end` |
| `scripts/fetch_period_data.py` | Create | Orchestrator: validates period, runs Top8 then Goldfish, prints summary |
| `tests/test_fetch_period_data.py` | Create | Tests for orchestrator's arg handling and subprocess call construction |
| `.claude/skills/top8-scraper/SKILL.md` | Modify | Document new flags, updated pipeline, orchestrator usage |
| `.claude/skills/goldfish-scraper/SKILL.md` | Modify | Document new flags, updated pipeline, orchestrator usage |

Files that change together: the two scrapers share `period_utils`. Files that change together: each scraper edit pairs with its own skill doc edit, but cross-skill updates are bundled into Task 5.

---

## Task 1: Shared period utility module

**Files:**
- Create: `scripts/period_utils.py`
- Create: `tests/test_period_utils.py`
- Test: `tests/test_period_utils.py`

**Depends on:** none

**Goal:** One module owns period detection and ISO date parsing. Both scrapers import from here, killing the duplicated `META_FILE` block.

### Step 1.1: Write failing tests for period_utils

Create `/Users/lianghaoming/mtg_agents_workplace/tests/test_period_utils.py`:

```python
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
```

### Step 1.2: Run tests to verify they fail

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_period_utils.py -v`
Expected: ModuleNotFoundError on `scripts.period_utils` — all tests fail (or error).

### Step 1.3: Implement scripts/period_utils.py

Create `/Users/lianghaoming/mtg_agents_workplace/scripts/period_utils.py`:

```python
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
    resolved_end = parse_iso_date(end) if end else (today or date.today()).isoformat()
    if resolved_start > resolved_end:
        raise ValueError(f"start ({resolved_start}) must be <= end ({resolved_end})")
    return PeriodArgs(start=resolved_start, end=resolved_end)
```

### Step 1.4: Run tests to verify they pass

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_period_utils.py -v`
Expected: 8 tests pass.

### Step 1.5: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace
git add scripts/period_utils.py tests/test_period_utils.py
git commit -m "feat(period): add shared period_utils for ban-window scrapers"
```

---

## Task 2: Top8 decklist scraper — accept `--start` / `--end` and stamp `period_end`

**Files:**
- Modify: `scrape_decklists_top8.py:26-35` (replace inline `PERIOD_START` block with import)
- Modify: `scrape_decklists_top8.py:311-320` (parse new flags, resolve period)
- Modify: `scrape_decklists_top8.py:444-461` (write `period_end` to output)
- Modify: `scrape_decklists_top8.py:359-369` (filter events by `[start, end]` instead of `[start, today]`)

**Depends on:** Task 1

**Goal:** Top8 scraper accepts `--start` / `--end`, filters events by the resolved period, and stamps both `period_start` and `period_end` into the output JSON.

### Step 2.1: Replace the inline `PERIOD_START` block

In `/Users/lianghaoming/mtg_agents_workplace/scrape_decklists_top8.py`, replace lines 26–35:

```python
# Auto-detect period start from meta.json (latest B&R update effective_date)
PERIOD_START = "2026-05-18"  # fallback
if META_FILE.exists():
    try:
        with open(META_FILE) as _f:
            _meta = json.load(_f)
        if "changes_history" in _meta and _meta["changes_history"]:
            PERIOD_START = _meta["changes_history"][-1].get("effective_date", PERIOD_START)
    except Exception:
        pass
```

with:

```python
# Period bounds are resolved in main() from --start / --end flags,
# defaulting start to ban_list/meta.json (latest B&R effective_date)
# and end to today. See scripts/period_utils.resolve_period_args.
DEFAULT_PERIOD_START = "2026-05-18"  # fallback when meta.json is missing
```

### Step 2.2: Add `resolve_period_args` to imports

In the import block at the top of `scrape_decklists_top8.py`, add the import (after the existing `from datetime import datetime` line):

```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.period_utils import resolve_period_args
```

### Step 2.3: Update the date-filter block in main()

In `scrape_decklists_top8.py`, find lines 359–369 (the date-filter check inside the per-event loop) and replace:

```python
                # Skip events before period start, and normalize date to ISO format
                event_date_iso = ""
                if event_info.get("date"):
                    try:
                        parts = event_info["date"].split("/")
                        event_date_iso = f"20{parts[2]}-{parts[1]}-{parts[0]}"
                        if event_date_iso < PERIOD_START:
                            print(f"  Skip (before period start {PERIOD_START})")
                            continue
                    except (IndexError, ValueError):
                        event_date_iso = event_info["date"]
```

with:

```python
                # Skip events outside the resolved [period_start, period_end] window,
                # and normalize date to ISO format
                event_date_iso = ""
                if event_info.get("date"):
                    try:
                        parts = event_info["date"].split("/")
                        event_date_iso = f"20{parts[2]}-{parts[1]}-{parts[0]}"
                        if event_date_iso < period_start:
                            print(f"  Skip (before period start {period_start})")
                            continue
                        if event_date_iso > period_end:
                            print(f"  Skip (after period end {period_end})")
                            continue
                    except (IndexError, ValueError):
                        event_date_iso = event_info["date"]
```

### Step 2.4: Resolve period and parse new flags in main()

Replace lines 311–320 in `scrape_decklists_top8.py` (the start of `def main()`):

```python
def main():
    from playwright.sync_api import sync_playwright

    max_events = int(sys.argv[sys.argv.index("--max-events") + 1]) if "--max-events" in sys.argv else 999
    skip_existing = "--skip-existing" in sys.argv
    start_arg = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else None
    end_arg = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else None

    period = resolve_period_args(
        start=start_arg,
        end=end_arg,
        meta_path=META_FILE,
        fallback=DEFAULT_PERIOD_START,
    )
    period_start, period_end = period.start, period.end

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} cards")
    print(f"Period: {period_start} ~ {period_end}")
```

### Step 2.5: Stamp `period_end` in the output JSON

In `scrape_decklists_top8.py`, find the output dict construction (around lines 444–460). Replace:

```python
    output = {
        "format": "Modern",
        "collected_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "MTGTop8",
        "period_start": PERIOD_START,
        "total_decks": len(all_decklists),
        "legal_decks": legality_report["legal"],
        "illegal_decks": legality_report["illegal"],
        "legality_report": legality_report,
        "decklists": all_decklists,
    }
```

with:

```python
    output = {
        "format": "Modern",
        "collected_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "MTGTop8",
        "period_start": period_start,
        "period_end": period_end,
        "total_decks": len(all_decklists),
        "legal_decks": legality_report["legal"],
        "illegal_decks": legality_report["illegal"],
        "legality_report": legality_report,
        "decklists": all_decklists,
    }
```

### Step 2.6: Smoke check (no Playwright import)

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -c "import scrape_decklists_top8; print('imports OK')"`
Expected: prints `imports OK` and no traceback. (Do NOT run the full scraper — Playwright launch is the slow part.)

### Step 2.7: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace
git add scrape_decklists_top8.py
git commit -m "feat(top8): accept --start/--end and stamp period_end in decklist output"
```

---

## Task 3: Goldfish two-phase scraper — accept `--start` / `--end` and stamp `period_end`

**Files:**
- Modify: `scrape_goldfish_two_phase.py:32-41` (replace inline `PERIOD_START` block)
- Modify: `scrape_goldfish_two_phase.py:283-308` (stamp `period_end` in `save_decklists`)
- Modify: `scrape_goldfish_two_phase.py:322-336` (parse new flags, resolve period)

**Depends on:** Task 1

**Goal:** Goldfish scraper accepts `--start` / `--end` and stamps both `period_start` and `period_end` into the decklist output JSON.

### Step 3.1: Replace the inline `PERIOD_START` block

In `/Users/lianghaoming/mtg_agents_workplace/scrape_goldfish_two_phase.py`, replace lines 32–41:

```python
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
PERIOD_START = "2026-05-18"
if META_FILE.exists():
    try:
        with open(META_FILE) as _f:
            _meta = json.load(_f)
        if "changes_history" in _meta and _meta["changes_history"]:
            PERIOD_START = _meta["changes_history"][-1].get("effective_date", PERIOD_START)
    except Exception:
        pass
```

with:

```python
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
DEFAULT_PERIOD_START = "2026-05-18"  # fallback when meta.json is missing
```

### Step 3.2: Add `resolve_period_args` to imports

After `from datetime import datetime` near the top of `scrape_goldfish_two_phase.py`, add:

```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.period_utils import resolve_period_args
```

### Step 3.3: Update `save_decklists` to take and stamp `period_end`

In `scrape_goldfish_two_phase.py`, change the signature of `save_decklists` (around line 283) from:

```python
def save_decklists(all_decklists: list, overlap_skipped: int, output_file: Path, banlist: set):
```

to:

```python
def save_decklists(all_decklists: list, overlap_skipped: int, output_file: Path, banlist: set, period_start: str, period_end: str):
```

and inside the function (around lines 287–308), replace the `period_start` line in the output dict:

```python
        "period_start": PERIOD_START,
```

with:

```python
        "period_start": period_start,
        "period_end": period_end,
```

### Step 3.4: Update the tournament-date filter

In `scrape_goldfish_two_phase.py`, find the block that uses `PERIOD_START` to build the search URL and tournament filter (around lines 393–400). Replace the hard-coded reference to `PERIOD_START` with the resolved `period_start` variable (renaming the local). Concretely, replace the two reads of `PERIOD_START` in this block with `period_start` and ensure the surrounding code reads:

```python
            today = datetime.now().strftime("%m/%d/%Y")
            ps = datetime.strptime(period_start, "%Y-%m-%d")
            period_start_fmt = ps.strftime("%m/%d/%Y")
            search_url = GOLDFISH_TOURNAMENT_SEARCH_URL.format(
                start=period_start_fmt, end=today
            )
```

Also update the print line (around line 332) from `print(f"Period: {PERIOD_START} ~ today")` to `print(f"Period: {period_start} ~ {period_end}")`.

### Step 3.5: Resolve period and parse new flags in main()

In `scrape_goldfish_two_phase.py`, in `def main()` (line 322), add flag parsing and period resolution. Replace the current top of `main()`:

```python
def main():
    max_tournaments = 999
    if "--max-tournaments" in sys.argv:
        idx = sys.argv.index("--max-tournaments")
        max_tournaments = int(sys.argv[idx + 1])

    resume = "--resume" in sys.argv
    skip_top8_overlap = "--skip-top8-overlap" in sys.argv

    print(f"=== MTGGoldfish Two-Phase Decklist Scraper ===")
    print(f"Period: {PERIOD_START} ~ today")
    print(f"Max tournaments: {max_tournaments}")
    print(f"Skip Top8 overlap: {skip_top8_overlap}")
    print(f"Resume: {resume}")
    print(f"Delay between tournaments: {DELAY_BETWEEN_TOURNAMENTS}s")

    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} banned cards")
```

with:

```python
def main():
    max_tournaments = 999
    if "--max-tournaments" in sys.argv:
        idx = sys.argv.index("--max-tournaments")
        max_tournaments = int(sys.argv[idx + 1])

    resume = "--resume" in sys.argv
    skip_top8_overlap = "--skip-top8-overlap" in sys.argv
    start_arg = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else None
    end_arg = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else None

    period = resolve_period_args(
        start=start_arg,
        end=end_arg,
        meta_path=META_FILE,
        fallback=DEFAULT_PERIOD_START,
    )
    period_start, period_end = period.start, period.end

    print(f"=== MTGGoldfish Two-Phase Decklist Scraper ===")
    print(f"Period: {period_start} ~ {period_end}")
    print(f"Max tournaments: {max_tournaments}")
    print(f"Skip Top8 overlap: {skip_top8_overlap}")
    print(f"Resume: {resume}")
    print(f"Delay between tournaments: {DELAY_BETWEEN_TOURNAMENTS}s")

    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} banned cards")
```

Also update the calls to `save_decklists` further down in `main()` so the new `period_start` / `period_end` keyword args are passed. Search for `save_decklists(` in the file and add the two keyword args to every call.

### Step 3.6: Smoke check

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -c "import scrape_goldfish_two_phase; print('imports OK')"`
Expected: prints `imports OK` and no traceback.

### Step 3.7: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace
git add scrape_goldfish_two_phase.py
git commit -m "feat(goldfish): accept --start/--end and stamp period_end in decklist output"
```

---

## Task 4: Period-fetch orchestrator

**Files:**
- Create: `scripts/fetch_period_data.py`
- Create: `tests/test_fetch_period_data.py`
- Test: `tests/test_fetch_period_data.py`

**Depends on:** Tasks 1, 2, 3

**Goal:** A single command runs both scrapers for one period, in the correct order, with the correct flag plumbing, and prints a summary.

### Step 4.1: Write failing tests for the orchestrator

Create `/Users/lianghaoming/mtg_agents_workplace/tests/test_fetch_period_data.py`:

```python
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
    assert args.end is None  # orchestrator passes "today" downstream


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


def test_build_commands_top8_then_goldfish(tmp_path: Path):
    """The Top8 scraper must be invoked first; Goldfish second with --skip-top8-overlap."""
    meta = tmp_path / "meta.json"
    cmds = fetch_period_data.build_commands(
        start="2026-05-18", end="2026-06-03", meta_path=meta
    )
    assert len(cmds) == 2
    top8, goldfish = cmds
    assert "scrape_decklists_top8.py" in top8[0]
    assert "--start" in top8 and "2026-05-18" in top8
    assert "--end" in top8 and "2026-06-03" in top8
    assert "scrape_goldfish_two_phase.py" in goldfish[0]
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
        "--dry-run",  # do not actually exec; we patched subprocess.run
    ])
    assert rc == 0
    assert mock_run.call_count == 2
    out = capsys.readouterr().out
    assert "MTGTop8" in out and "MTGGoldfish" in out


@patch("scripts.fetch_period_data.subprocess.run")
def test_main_aborts_if_top8_fails(mock_run, tmp_path):
    (tmp_path / "meta.json").write_text('{"changes_history": [{"effective_date": "2026-05-18"}]}')
    mock_run.side_effect = [
        __import__("subprocess").CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"),
        __import__("subprocess").CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]
    rc = fetch_period_data.main([
        "--meta", str(tmp_path / "meta.json"),
        "--start", "2026-05-18", "--end", "2026-06-03",
        "--dry-run",
    ])
    assert rc == 1
    # Goldfish must not run if Top8 failed
    assert mock_run.call_count == 1
```

### Step 4.2: Run tests to verify they fail

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_fetch_period_data.py -v`
Expected: ModuleNotFoundError on `scripts.fetch_period_data` — tests error.

### Step 4.3: Implement scripts/fetch_period_data.py

Create `/Users/lianghaoming/mtg_agents_workplace/scripts/fetch_period_data.py`:

```python
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
from typing import Sequence

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

    period = resolve_period_args(
        start=args.start, end=args.end,
        meta_path=Path(args.meta), fallback=fallback,
    )
    args.start, args.end = period.start, period.end
    return args


def build_commands(start: str, end: str, meta_path: Path,
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    print(f"=== Period Data Fetch ===")
    print(f"Period: {args.start} ~ {args.end}")
    print(f"Meta:   {args.meta}")

    commands = build_commands(
        start=args.start, end=args.end, meta_path=Path(args.meta),
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
```

### Step 4.4: Run tests to verify they pass

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_fetch_period_data.py -v`
Expected: 5 tests pass.

### Step 4.5: Smoke check the CLI

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 scripts/fetch_period_data.py --start 2026-05-18 --end 2026-06-03 --dry-run`
Expected: prints `=== Period Data Fetch ===`, both scraper command lines, `--- Done ---`. No actual scraping happens.

### Step 4.6: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace
git add scripts/fetch_period_data.py tests/test_fetch_period_data.py
git commit -m "feat(period): add fetch_period_data orchestrator for Top8 + Goldfish"
```

---

## Task 5: Update both skill SKILL.md docs

**Files:**
- Modify: `.claude/skills/top8-scraper/SKILL.md`
- Modify: `.claude/skills/goldfish-scraper/SKILL.md`

**Depends on:** Tasks 1–4

**Goal:** Skills reflect the new flags and the new orchestrator entry point.

### Step 5.1: Update top8 skill

In `/Users/lianghaoming/mtg_agents_workplace/.claude/skills/top8-scraper/SKILL.md`, add a new section after the existing "CLI Flags" table. Find the existing flags table and add two rows:

```markdown
| `--start YYYY-MM-DD` | `meta.json` latest B&R | Only include events on/after this date. |
| `--end YYYY-MM-DD`   | today                  | Only include events on/before this date. |
```

Then update the "Pipeline Position" block to add the orchestrator as the recommended entry point. Replace the existing block:

```markdown
## Pipeline Position

```bash
python3 scrape_decklists_top8.py --max-events 999     # 1. Top8 decklists
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap  # 2. Goldfish
python3 evaluate_deck_strength.py --top 15             # 3. Fuse + strength
python3 scripts/build_card_impact.py                   # 4. Card impact
python3 compose_meta.py                                # 5. Meta + matchup
```
```

with:

```markdown
## Pipeline Position

For a single-shot period refresh (recommended):

```bash
python3 scripts/fetch_period_data.py                  # current period, both sources
python3 scripts/fetch_period_data.py --start 2026-05-18 --end 2026-06-03  # explicit
```

To run sources individually:

```bash
python3 scrape_decklists_top8.py --max-events 999                     # 1. Top8
python3 scrape_goldfish_two_phase.py --resume --skip-top8-overlap     # 2. Goldfish
python3 evaluate_deck_strength.py --top 15                            # 3. Fuse + strength
python3 scripts/build_card_impact.py                                  # 4. Card impact
python3 compose_meta.py                                               # 5. Meta + matchup
```

Both scrapers stamp `period_start` and `period_end` into the output JSON so downstream
consumers can identify the data window without inferring from `collected_date`.
```

### Step 5.2: Update goldfish skill

In `/Users/lianghaoming/mtg_agents_workplace/.claude/skills/goldfish-scraper/SKILL.md`, add a new row to the CLI Flags table for `--start` and `--end` (with the same descriptions as the top8 skill), and update the "Pipeline Position" block to mirror the top8 skill's orchestrator-first layout.

Find the existing flags table and add after the last existing row:

```markdown
| `--start YYYY-MM-DD` | `meta.json` latest B&R | Only include tournaments on/after this date. |
| `--end YYYY-MM-DD`   | today                  | Only include tournaments on/before this date. |
```

Replace the "Pipeline Position" block with the same orchestrator-first version used in the top8 skill.

### Step 5.3: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace
git add .claude/skills/top8-scraper/SKILL.md .claude/skills/goldfish-scraper/SKILL.md
git commit -m "docs(skills): document --start/--end flags and period orchestrator"
```

---

## Task 6: End-to-end validation

**Files:** none (no code changes)

**Depends on:** Tasks 1–5

**Goal:** Confirm the new flag plumbing works without launching a real browser.

### Step 6.1: Run the full test suite

Run: `cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/ -v`
Expected: all tests pass (the new 8 + 5 = 13 tests plus the existing 3 MTGO tests = 16 total).

### Step 6.2: Validate the orchestrator's CLI end-to-end (dry-run)

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace
python3 scripts/fetch_period_data.py --start 2026-05-18 --end 2026-06-03 --dry-run
```
Expected: prints both scraper commands with the correct `--start 2026-05-18 --end 2026-06-03` flags, no errors, exits 0.

### Step 6.3: Validate flag plumbing in Top8 scraper

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace
python3 scrape_decklists_top8.py --start 2026-05-18 --end 2026-06-03 2>&1 | head -10
```
Expected: prints `Period: 2026-05-18 ~ 2026-06-03` near the top before Playwright boots. (Cancel with Ctrl-C once the period line is visible; the goal is to confirm the flag is accepted, not to run a full scrape.)

### Step 6.4: Commit (no changes)

If any test or smoke run surfaced a fix, commit it with a message describing the fix. Otherwise: nothing to commit.

---

## Self-Review

**1. Spec coverage**
- Shared period parsing → Task 1
- Top8 accepts `--start` / `--end` and stamps `period_end` → Task 2
- Goldfish accepts `--start` / `--end` and stamps `period_end` → Task 3
- Single orchestrator entry point → Task 4
- Skill docs reflect new flags and orchestrator → Task 5
- End-to-end validation → Task 6

**2. Placeholder scan**
- No "TBD" / "TODO" / "implement later" anywhere.
- All CLI args and their defaults are concrete.
- All test bodies are full code, not "similar to Task N".

**3. Type consistency**
- `PeriodArgs.start` / `PeriodArgs.end` (str) used consistently in `period_utils` and orchestrator.
- `period_start` / `period_end` (str locals) used in both scrapers.
- `scrape_decklists_top8.py` and `scrape_goldfish_two_phase.py` both use the same flag names (`--start`, `--end`) and the same `resolve_period_args` signature.

No issues found.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-period-data-fetch.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

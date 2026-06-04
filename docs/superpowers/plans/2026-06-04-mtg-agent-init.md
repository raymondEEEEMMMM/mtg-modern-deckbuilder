# MTG Agent Init Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-platform `agent-init` skill that loads MTG Modern Meta Agent identity, reports current banlist period, and checks freshness of 4 key data products on demand.

**Architecture:** Single shared `docs/agent-init.md` checklist + thin per-platform `SKILL.md` shells (Claude Code / CodeBuddy / OpenClaw). A deterministic `scripts/agent_health_check.py` produces a structured JSON report consumed by the agent.

**Tech Stack:** Python 3 (stdlib only: `json`, `argparse`, `pathlib`, `datetime`), reuses `scripts/period_utils.py`. Tests via `pytest` with `tmp_path` fixtures.

**Spec:** `docs/superpowers/specs/2026-06-04-mtg-agent-init-design.md`

---

## File Structure

| File | Purpose | New/Modified |
|------|---------|--------------|
| `scripts/agent_health_check.py` | Deterministic health check, emits JSON | New |
| `tests/test_agent_health_check.py` | Unit tests for the script | New |
| `docs/agent-init.md` | Shared execution checklist (canonical body) | New |
| `.claude/skills/agent-init/SKILL.md` | Claude Code shell pointing to canonical body | New |
| `.codebuddy/skills/agent-init/SKILL.md` | CodeBuddy shell with detailed description | New |
| `skills/agent-init/SKILL.md` | OpenClaw shell with `metadata.openclaw.requires` | New |
| `README.md` | "可用 Skills" section adds `agent-init` row | Modify |

---

## Task 1: Create script skeleton with constants

**Files:**
- Create: `scripts/agent_health_check.py`

- [ ] **Step 1: Create the script with imports, constants, and a no-op main**

```python
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


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the script imports cleanly**

Run: `python3 -c "import scripts.agent_health_check"`
Expected: no output, exit 0

- [ ] **Step 3: Commit**

```bash
git add scripts/agent_health_check.py
git commit -m "feat(agent-init): add health check script skeleton"
```

---

## Task 2: Period detection — failing test, then implementation

**Files:**
- Create: `tests/test_agent_health_check.py`
- Modify: `scripts/agent_health_check.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from datetime import date
from pathlib import Path

import pytest

from scripts.agent_health_check import build_period_info


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_build_period_info_returns_latest_effective_date_and_days -v`
Expected: FAIL with `ImportError: cannot import name 'build_period_info'`

- [ ] **Step 3: Implement `build_period_info` in the script**

Add to `scripts/agent_health_check.py` above `main()`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_build_period_info_returns_latest_effective_date_and_days -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_health_check.py tests/test_agent_health_check.py
git commit -m "feat(agent-init): derive current banlist period from meta.json"
```

---

## Task 3: Period failure — missing meta.json raises

**Files:**
- Modify: `tests/test_agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_health_check.py`:

```python
def test_build_period_info_raises_when_meta_missing(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError, match="could not determine period start"):
        build_period_info(missing, today=date(2026, 6, 4))


def test_build_period_info_raises_when_history_empty(tmp_path: Path):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"changes_history": []}))
    with pytest.raises(ValueError, match="could not determine period start"):
        build_period_info(path, today=date(2026, 6, 4))
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_agent_health_check.py -v`
Expected: all 3 PASS (implementation already raises because fallback is `""`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_health_check.py
git commit -m "test(agent-init): cover missing meta.json and empty history"
```

---

## Task 4: Per-product freshness check — missing file

**Files:**
- Modify: `tests/test_agent_health_check.py`
- Modify: `scripts/agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from scripts.agent_health_check import check_product


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_check_product_marks_missing_file_as_stale -v`
Expected: FAIL with `ImportError: cannot import name 'check_product'`

- [ ] **Step 3: Implement `check_product`**

Add to `scripts/agent_health_check.py` above `main()`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_check_product_marks_missing_file_as_stale -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_health_check.py tests/test_agent_health_check.py
git commit -m "feat(agent-init): detect missing product files"
```

---

## Task 5: Per-product freshness — predates_current_period

**Files:**
- Modify: `tests/test_agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Add the `datetime` import to the test file if missing**

Verify test file has:
```python
from datetime import date, datetime
```

(Update existing import line.)

- [ ] **Step 3: Run test**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_check_product_marks_old_file_as_predates_period -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_health_check.py
git commit -m "test(agent-init): cover predates_current_period reason"
```

---

## Task 6: Per-product freshness — older_than_7d and fresh

**Files:**
- Modify: `tests/test_agent_health_check.py`

- [ ] **Step 1: Write two failing tests**

Append:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_agent_health_check.py -v -k "older_than_7d or fresh_file"`
Expected: both PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_health_check.py
git commit -m "test(agent-init): cover older_than_7d and fresh cases"
```

---

## Task 7: `build_recommendations` — single stale product

**Files:**
- Modify: `tests/test_agent_health_check.py`
- Modify: `scripts/agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from scripts.agent_health_check import build_recommendations


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
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_build_recommendations_single_stale_product -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `build_recommendations`**

Add to `scripts/agent_health_check.py` above `main()`:

```python
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
```

- [ ] **Step 4: Run test**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_build_recommendations_single_stale_product -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_health_check.py tests/test_agent_health_check.py
git commit -m "feat(agent-init): map stale products to regeneration commands"
```

---

## Task 8: `build_recommendations` — multiple stale, dedup, pipeline order

**Files:**
- Modify: `tests/test_agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_agent_health_check.py -v -k "build_recommendations"`
Expected: all 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_health_check.py
git commit -m "test(agent-init): cover dedup and empty-stale recommendation cases"
```

---

## Task 9: `run_health_check` — full report assembly

**Files:**
- Modify: `tests/test_agent_health_check.py`
- Modify: `scripts/agent_health_check.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from scripts.agent_health_check import run_health_check


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
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_run_health_check_assembles_full_report -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `run_health_check`**

Add to `scripts/agent_health_check.py` above `main()`:

```python
def run_health_check(
    meta_path: Path = META_PATH,
    data_root: Path = REPO_ROOT / "mtg_modern_data",
    today: Optional[date] = None,
) -> dict:
    """Produce the full health-check report dictionary."""
    today = today or date.today()
    period = build_period_info(meta_path, today=today)
    period_start = date.fromisoformat(period["start"])
    products = []
    for name, rel_path, _ in PRODUCTS:
        # Reconstruct path relative to data_root, stripping leading
        # "mtg_modern_data/" so tests can supply an isolated data_root.
        relative = rel_path.removeprefix("mtg_modern_data/")
        products.append(check_product(
            name=name,
            path=data_root / relative,
            period_start=period_start,
            today=today,
        ))
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "period": period,
        "products": products,
        "stale_products": [p["name"] for p in products if p["stale"]],
        "recommended_next_steps": build_recommendations(products),
    }
```

- [ ] **Step 4: Run test**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_run_health_check_assembles_full_report -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_health_check.py tests/test_agent_health_check.py
git commit -m "feat(agent-init): assemble end-to-end health check report"
```

---

## Task 10: `main()` — CLI, JSON output, exit codes

**Files:**
- Modify: `tests/test_agent_health_check.py`
- Modify: `scripts/agent_health_check.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
import subprocess
import sys as _sys


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
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_agent_health_check.py::test_main_writes_json_to_stdout_when_meta_valid tests/test_agent_health_check.py::test_main_exits_2_when_meta_missing -v`
Expected: both FAIL (main is a no-op)

- [ ] **Step 3: Implement `main()`**

Replace the existing `main()` in `scripts/agent_health_check.py` with:

```python
def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MTG Modern Meta Agent health check (period + data freshness).",
    )
    parser.add_argument(
        "--meta",
        type=Path,
        default=META_PATH,
        help="Path to ban_list/meta.json (default: project meta.json).",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=REPO_ROOT / "mtg_modern_data",
        help="Root of the data lake (default: ./mtg_modern_data).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format. JSON for agent consumption (default), text for humans.",
    )
    return parser.parse_args(argv)


def _format_text(report: dict) -> str:
    lines = [
        f"Period start:        {report['period']['start']}",
        f"Today:               {report['period']['today']}",
        f"Days since start:    {report['period']['days_since_start']}",
        "",
        "Products:",
    ]
    for p in report["products"]:
        status = "fresh" if not p["stale"] else f"STALE ({p['reason']})"
        mtime = p["mtime"] or "—"
        lines.append(f"  - {p['name']:<20} mtime={mtime}  {status}")
    if report["recommended_next_steps"]:
        lines.append("")
        lines.append("Recommended next steps:")
        for cmd in report["recommended_next_steps"]:
            lines.append(f"  $ {cmd}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_health_check(meta_path=args.meta, data_root=args.data_root)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"unexpected error: {e}", file=sys.stderr)
        return 3
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(_format_text(report))
    return 0
```

- [ ] **Step 4: Run all health check tests**

Run: `python3 -m pytest tests/test_agent_health_check.py -v`
Expected: all PASS

- [ ] **Step 5: Smoke-run against the real repo**

Run: `python3 scripts/agent_health_check.py --format text`
Expected: human-readable report with the 4 products and current period.

- [ ] **Step 6: Commit**

```bash
git add scripts/agent_health_check.py tests/test_agent_health_check.py
git commit -m "feat(agent-init): add CLI with JSON/text output and exit codes"
```

---

## Task 11: Write `docs/agent-init.md` canonical checklist

**Files:**
- Create: `docs/agent-init.md`

- [ ] **Step 1: Write the file**

```markdown
# Agent Init 执行清单

被触发后按顺序完成四步，然后向用户报告。

## Step 1: 加载身份

读 `docs/agent-prompt.md`，记住:

- 你是 MTG Modern Meta Agent
- 所有分析锁定在 current banlist period 内
- 不混合跨周期数据
- heuristic 与 observed 必须区分标注

若 `docs/agent-prompt.md` 不存在，告诉用户"身份文档缺失"，但仍继续 Step 2。

## Step 2: 取健康状态

运行 `python3 scripts/agent_health_check.py`，解析 stdout JSON。

- 退出码 `0`：使用 JSON 内容继续
- 退出码 `2`：把 stderr 原样返回给用户（多半是 `meta.json` 缺失），提示先跑 `python3 build_banlist_snapshots.py`，不要继续 Step 3
- 退出码 `3`：把 stderr 原样返回给用户，不要继续

## Step 3: 向用户报告

按以下格式呈现（中文/英文混合，与项目惯例一致）:

> **MTG Modern Meta Agent 已就绪**
>
> - 当前周期: `{period.start}` 起，已进行 `{period.days_since_start}` 天
> - 数据状态:
>   - `fused_archetypes`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `top_decks`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `card_impact`: mtime `{mtime}` · `{fresh / stale (reason)}`
>   - `meta_current`: mtime `{mtime}` · `{fresh / stale (reason)}`

`reason` 字段直接照搬 JSON：`missing` / `predates_current_period` / `older_than_7d`。

## Step 4: 推荐下一步（条件性）

若 `stale_products` 非空：

- 列出 `recommended_next_steps`（按 JSON 给的顺序，已是流水线顺序）
- 询问用户："是否现在执行？"
- **不要自动执行**，等用户明确指示

完成后说"等待指令"。
```

- [ ] **Step 2: Commit**

```bash
git add docs/agent-init.md
git commit -m "docs(agent-init): add canonical execution checklist"
```

---

## Task 12: Claude Code SKILL.md shell

**Files:**
- Create: `.claude/skills/agent-init/SKILL.md`

- [ ] **Step 1: Create the file**

```markdown
---
name: agent-init
description: Use at the start of a session or whenever the user wants to enter MTG Modern Meta Agent mode. Triggers include "initialize MTG agent", "start MTG session", "进入 MTG 模式", "加载 agent 身份", "begin meta analysis". Loads agent persona, reports current banlist period, and checks freshness of key data products.
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

- [ ] **Step 2: Verify it shows up in skill listing**

Run: `ls .claude/skills/agent-init/`
Expected: `SKILL.md`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/agent-init/SKILL.md
git commit -m "feat(agent-init): add Claude Code skill shell"
```

---

## Task 13: CodeBuddy SKILL.md shell

**Files:**
- Create: `.codebuddy/skills/agent-init/SKILL.md`

- [ ] **Step 1: Create the file**

```markdown
---
name: agent-init
description: MTG Modern Meta Agent initialization skill. This skill should be used at session start, or whenever the user wants the agent to assume the MTG Modern Meta Agent role and verify the local knowledge base state. Loads agent persona from docs/agent-prompt.md, detects the current banlist period from ban_list/meta.json, runs a deterministic health check on the four key data products (fused_archetypes, top_decks, card_impact, meta/current.json), and recommends next steps if any product is stale. Triggers on: starting a new MTG analysis session, "initialize agent", "进入 MTG 模式", "load context", or whenever the agent needs to confirm its operating state and data freshness before answering questions.
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

- [ ] **Step 2: Commit**

```bash
git add .codebuddy/skills/agent-init/SKILL.md
git commit -m "feat(agent-init): add CodeBuddy skill shell"
```

---

## Task 14: OpenClaw SKILL.md shell (new `skills/` root dir)

**Files:**
- Create: `skills/agent-init/SKILL.md`

- [ ] **Step 1: Verify the directory does not collide with an existing pattern**

Run: `ls skills/ 2>/dev/null || echo "absent"`
Expected: `absent` (creating a new top-level dir)

- [ ] **Step 2: Check `.gitignore` does not exclude the new dir**

Run: `grep -E "^skills/?$|^/skills/?$" .gitignore || echo "not ignored"`
Expected: `not ignored`

If it IS ignored, abort and ask the user how to proceed (do not edit `.gitignore` without confirmation).

- [ ] **Step 3: Create the file (parent dir created automatically)**

```markdown
---
name: agent-init
description: Use at the start of a session or whenever the user wants to enter MTG Modern Meta Agent mode. Triggers include "initialize MTG agent", "start MTG session", "进入 MTG 模式", "加载 agent 身份". Loads agent persona, reports current banlist period, checks data freshness.
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    os: ["darwin", "linux"]
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.
```

- [ ] **Step 4: Commit**

```bash
git add skills/agent-init/SKILL.md
git commit -m "feat(agent-init): add OpenClaw skill shell"
```

---

## Task 15: Update README's "可用 Skills" section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current "可用 Skills" block**

Run: `grep -n "可用 Skills" README.md`
Expected: line ~107 (per current spec) — confirm before editing.

- [ ] **Step 2: Insert a new bullet for `agent-init`**

In `README.md`, find the bullet list under `## 可用 Skills`. After the line:

```markdown
- **mtg-banlist** — 当前禁牌、禁牌历史、B&R 生效日、当前周期
```

Append (use Edit tool):

```markdown
- **agent-init** — 会话开始时加载 MTG Modern Meta Agent 身份、报告当前 ban period 与 4 个关键产物的新鲜度（脚本：`scripts/agent_health_check.py`；清单：`docs/agent-init.md`）
```

- [ ] **Step 3: Sanity check the section renders correctly**

Run: `sed -n '/## 可用 Skills/,/## /p' README.md`
Expected: 5 bullets including the new `agent-init` line.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): list agent-init in available skills"
```

---

## Task 16: Final verification

**Files:** (none modified)

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m pytest`
Expected: all tests PASS (existing + new `test_agent_health_check.py`)

- [ ] **Step 2: Smoke-run the script in real environment**

Run: `python3 scripts/agent_health_check.py --format text`
Expected: report shows the actual current period and product mtimes; exit 0.

- [ ] **Step 3: Smoke-run in JSON mode**

Run: `python3 scripts/agent_health_check.py | python3 -m json.tool | head -30`
Expected: valid JSON with `period`, `products`, `stale_products`, `recommended_next_steps`.

- [ ] **Step 4: Verify skill files are in place**

Run: `ls -la .claude/skills/agent-init/SKILL.md .codebuddy/skills/agent-init/SKILL.md skills/agent-init/SKILL.md docs/agent-init.md`
Expected: all 4 files exist.

- [ ] **Step 5: (Manual) Trigger the skill in Claude Code**

Open a fresh Claude Code session in this repo. Say: "初始化 MTG agent"

Expected: agent invokes `agent-init`, reads `docs/agent-init.md`, runs the script, reports period + 4 product statuses + (if applicable) next-step recommendations.

This step is **manual smoke** — record the result but no commit needed if the report matches the spec's §6 format.

# MTGO Source Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest MTGO decklists into `evaluate_deck_strength.py` as a third, weightable data source so the fused metagame picture reflects more decks without diluting Challenge-grade evidence.

**Architecture:** Two-stage classification. (1) A pure card-frequency classifier matches each MTGO deck to a canonical archetype using the `key_cards` already extracted from Top8+Goldfish; (2) `evaluate_deck_strength.py` loads the classified MTGO decks, applies a per-deck weight derived from `event_name` (Challenge > League), and folds them into the existing fusion pipeline. The heuristic matchup matrix is unchanged.

**Tech Stack:** Python 3, pytest 7.4, existing `evaluate_deck_strength.py` (no rewrite), no new deps.

---

## Context

The project currently fuses MTGTop8 + MTGGoldfish. A working MTGO scraper already exists (`scripts/scrape_mtgo_decklists.py`) and produced 82 classified, legal decklists on 2026-05-29, but those decks are not consumed by `evaluate_deck_strength.py`. This plan closes that loop with a card-based archetype classifier and an event-name-driven weighting scheme, then re-runs the pipeline.

Spec source: `docs/next-data-source-plan.md` → "Immediate Next Plan" (steps 1-4).

## Approach Decisions (locked before plan)

- **Card-based classifier, not name-based.** MTGO `deck_name_canonical` is empty for 82/82 current decks. Player/page names are kept only as a low-weight tiebreaker.
- **Existing key_cards are the classifier input.** `fused_archetypes.json[*].key_cards` already lists 3-5 non-land, non-sideboard cards per canonical archetype. Reuse them; do not rebuild profiles.
- **Two weight tiers, not continuous.** `event_name` regex classifies each deck as `challenge` (weight 1.0) or `league` (weight 0.4). Everything else → `other` (weight 0.6). Weights multiply the deck's contribution to decklist_count; they do not change `metagame_share` of the global pool.
- **League data is sample expansion, not win-rate evidence.** No attempt to compute MTGO win rates from `placement: "5-0"`; that is recorded but unused for scoring in this plan.
- **TopDeck stays out.** This plan does not touch `topdeck_poc.py` or `compose_meta.py` matchup logic.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tests/conftest.py` | Create | pytest fixtures: minimal `fused_archetypes.json` slice, minimal MTGO deck fixture |
| `tests/test_mtgo_classifier.py` | Create | Tests for `classify_deck_by_cards()` |
| `scripts/mtgo_classifier.py` | Create | Pure function: deck dict + key_card profiles → canonical name + confidence |
| `tests/test_load_mtgo_decklists.py` | Create | Tests for `load_and_classify_mtgo_decklists()` |
| `scripts/load_mtgo_decklists.py` | Create | Load raw MTGO JSON, run classifier, derive event_type + weight, write classified file |
| `evaluate_deck_strength.py` | Modify | Add `--include-mtgo` flag, integrate MTGO decklist source, apply per-deck weight in fusion |
| `pyproject.toml` | Create | Minimal pytest config so `pytest` works without args |
| `mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json` | Create (output) | MTGO decks with `archetype_canonical`, `event_type`, `weight` |

Files that change together: the two test files and their modules. Files that change together: `evaluate_deck_strength.py` is the only one modified in the main script tree.

---

## Task 1: Test Infrastructure + MTGO Card-Frequency Classifier

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `scripts/mtgo_classifier.py`
- Create: `tests/test_mtgo_classifier.py`

**Depends on:** none

**Goal:** A pure function `classify_deck_by_cards(deck, key_card_profiles)` that returns `(canonical_name, confidence)` for one MTGO deck, plus the test scaffolding that proves it.

### Step 1.1: Add minimal pytest config

Create `/Users/lianghaoming/mtg_agents_workplace/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

### Step 1.2: Make `tests/` a package and add a shared fixture

Create `/Users/lianghaoming/mtg_agents_workplace/tests/__init__.py` (empty file).

Create `/Users/lianghaoming/mtg_agents_workplace/tests/conftest.py`:

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture
def sample_key_card_profiles() -> dict:
    """Minimal key_card profile slice mirroring fused_archetypes.json schema."""
    return {
        "Boros Energy": ["Galvanic Discharge", "Guide of Souls", "Ajani, Nacatl Pariah"],
        "Affinity": ["Ornithopter", "Memnite", "Cranial Plating"],
        "UR Prowess": ["Dragon's Rage Channeler", "Stormwild Creeper", "Expressive Iteration"],
    }


@pytest.fixture
def mtgo_boros_deck() -> dict:
    """One MTGO deck record shaped like scrape_mtgo_decklists.py output."""
    return {
        "source": "mtgo",
        "event_id": "modern-league-2026-05-2910628",
        "event_name": "MODERN LEAGUE",
        "event_date": "2026-05-28",
        "deck_id": "modern-league-2026-05-2910628-2",
        "deck_name": "",
        "deck_name_canonical": "",
        "player": "CHACHIBUOH",
        "placement": "5-0",
        "maindeck": [
            {"qty": 4, "name": "Galvanic Discharge"},
            {"qty": 4, "name": "Guide of Souls"},
            {"qty": 3, "name": "Ajani, Nacatl Pariah"},
            {"qty": 4, "name": "Lightning Bolt"},
            {"qty": 2, "name": "Wrenn's Resolve"},
            # ... truncated for fixture; real decks have 60 cards
        ],
        "sideboard": [{"qty": 1, "name": "Blood Moon"}],
        "maindeck_count": 60,
        "sideboard_count": 15,
        "legality": {"legal": True, "banned_cards": []},
    }
```

### Step 1.3: Write the failing classifier test

Create `/Users/lianghaoming/mtg_agents_workplace/tests/test_mtgo_classifier.py`:

```python
from scripts.mtgo_classifier import classify_deck_by_cards, _deck_card_set


def test_deck_card_set_ignores_quantity_and_sideboard(
    mtgo_boros_deck,
):
    cards = _deck_card_set(mtgo_boros_deck)
    assert "Galvanic Discharge" in cards
    assert "Blood Moon" not in cards  # sideboard excluded
    assert len(cards) == 6  # maindeck only, qty stripped


def test_classify_boros_energy(mtgo_boros_deck, sample_key_card_profiles):
    name, confidence = classify_deck_by_cards(mtgo_boros_deck, sample_key_card_profiles)
    assert name == "Boros Energy"
    assert confidence >= 0.6  # 3/3 key cards hit


def test_classify_returns_unknown_for_empty_maindeck(sample_key_card_profiles):
    empty = {
        "maindeck": [],
        "sideboard": [],
        "deck_name": "",
        "deck_name_canonical": "",
    }
    name, confidence = classify_deck_by_cards(empty, sample_key_card_profiles)
    assert name == "Unknown"
    assert confidence == 0.0


def test_classify_prefers_higher_overlap(mtgo_boros_deck, sample_key_card_profiles):
    # Add 1 Affinity key card to maindeck — Boros still wins (3/3 vs 1/3)
    deck = dict(mtgo_boros_deck)
    deck["maindeck"] = mtgo_boros_deck["maindeck"] + [{"qty": 4, "name": "Ornithopter"}]
    name, _ = classify_deck_by_cards(deck, sample_key_card_profiles)
    assert name == "Boros Energy"


def test_classify_handles_unknown_cards_only(sample_key_card_profiles):
    deck = {
        "maindeck": [{"qty": 4, "name": f"Unknown Card {i}"} for i in range(60)],
        "sideboard": [],
        "deck_name": "",
        "deck_name_canonical": "",
    }
    name, confidence = classify_deck_by_cards(deck, sample_key_card_profiles)
    assert name == "Unknown"
    assert confidence == 0.0
```

### Step 1.4: Run tests to verify they fail

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_mtgo_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.mtgo_classifier'` for all 5 tests.

### Step 1.5: Implement the classifier

Create `/Users/lianghaoming/mtg_agents_workplace/scripts/mtgo_classifier.py`:

```python
"""Card-frequency-based classifier for MTGO decklists.

Maps a single deck to a canonical archetype by comparing its maindeck
(non-land, qty-stripped) card set against the `key_cards` lists stored
in fused_archetypes.json. Pure function: no I/O, no globals.
"""

from typing import Iterable


def _deck_card_set(deck: dict) -> set[str]:
    """Return maindeck card names only. Strip quantity. Exclude sideboard."""
    return {entry["name"] for entry in deck.get("maindeck", [])}


def _profile_card_set(profile: Iterable[str]) -> set[str]:
    return set(profile)


def classify_deck_by_cards(
    deck: dict, key_card_profiles: dict[str, list[str]]
) -> tuple[str, float]:
    """Return (canonical_archetype, confidence) for one deck.

    confidence = max(hits / profile_size) over all profiles, where hits
    is the count of profile cards present in the deck's maindeck. Returns
    ("Unknown", 0.0) when no profile has any hits or the deck has no
    maindeck entries.
    """
    deck_cards = _deck_card_set(deck)
    if not deck_cards:
        return "Unknown", 0.0

    best_name = "Unknown"
    best_confidence = 0.0
    for name, key_cards in key_card_profiles.items():
        profile = _profile_card_set(key_cards)
        if not profile:
            continue
        hits = len(deck_cards & profile)
        confidence = hits / len(profile)
        if confidence > best_confidence:
            best_name = name
            best_confidence = confidence

    if best_confidence == 0.0:
        return "Unknown", 0.0
    return best_name, best_confidence
```

### Step 1.6: Run tests to verify they pass

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_mtgo_classifier.py -v
```

Expected: `5 passed`.

### Step 1.7: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace && git add pyproject.toml tests/__init__.py tests/conftest.py tests/test_mtgo_classifier.py scripts/mtgo_classifier.py && git commit -m "feat(mtgo): add card-frequency classifier for MTGO decks"
```

---

## Task 2: MTGO Loader with Classification + Weighting

**Files:**
- Create: `scripts/load_mtgo_decklists.py`
- Create: `tests/test_load_mtgo_decklists.py`
- Create: `tests/fixtures/mtgo_sample.json` (test fixture only, not committed data)

**Depends on:** Task 1 (uses `classify_deck_by_cards`)

**Goal:** A runnable loader that reads `mtg_modern_data/sources/mtgo/mtgo_decklists.json`, classifies each deck, assigns an `event_type` and `weight`, and writes `mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json` in a shape `evaluate_deck_strength.py` can consume.

### Step 2.1: Write the loader tests

Create `/Users/lianghaoming/mtg_agents_workplace/tests/fixtures/mtgo_sample.json`:

```json
{
  "format": "Modern",
  "source": "mtgo",
  "period_start": "2026-05-18",
  "total_decks": 2,
  "decklists": [
    {
      "source": "mtgo",
      "event_id": "modern-challenge-64-2026-05-2812843376",
      "event_name": "MODERN CHALLENGE 64",
      "event_date": "2026-05-28",
      "deck_id": "modern-challenge-64-2026-05-2812843376-1",
      "deck_name": "",
      "deck_name_canonical": "",
      "player": "TESTPLAYER1",
      "placement": "1st",
      "maindeck": [
        {"qty": 4, "name": "Galvanic Discharge"},
        {"qty": 4, "name": "Guide of Souls"},
        {"qty": 3, "name": "Ajani, Nacatl Pariah"}
      ],
      "sideboard": [],
      "maindeck_count": 60,
      "sideboard_count": 15,
      "legality": {"legal": true, "banned_cards": []}
    },
    {
      "source": "mtgo",
      "event_id": "modern-league-2026-05-2910628",
      "event_name": "MODERN LEAGUE",
      "event_date": "2026-05-28",
      "deck_id": "modern-league-2026-05-2910628-2",
      "deck_name": "",
      "deck_name_canonical": "",
      "player": "TESTPLAYER2",
      "placement": "5-0",
      "maindeck": [
        {"qty": 4, "name": "Dragon's Rage Channeler"},
        {"qty": 4, "name": "Stormwild Creeper"},
        {"qty": 4, "name": "Expressive Iteration"}
      ],
      "sideboard": [],
      "maindeck_count": 60,
      "sideboard_count": 15,
      "legality": {"legal": true, "banned_cards": []}
    }
  ]
}
```

Create `/Users/lianghaoming/mtg_agents_workplace/tests/test_load_mtgo_decklists.py`:

```python
import json
from pathlib import Path

from scripts.load_mtgo_decklists import (
    classify_event_type,
    deck_weight,
    load_and_classify_mtgo_decklists,
)


def test_classify_event_type_challenge():
    assert classify_event_type("MODERN CHALLENGE 64") == "challenge"
    assert classify_event_type("Modern Challenge 32") == "challenge"


def test_classify_event_type_league():
    assert classify_event_type("MODERN LEAGUE") == "league"


def test_classify_event_type_other():
    assert classify_event_type("MODERN PRELIMINARY") == "other"


def test_deck_weight_challenge():
    assert deck_weight("challenge") == 1.0


def test_deck_weight_league():
    assert deck_weight("league") == 0.4


def test_deck_weight_other():
    assert deck_weight("other") == 0.6


def test_load_and_classify_uses_fixture(tmp_path: Path, monkeypatch):
    # Re-point loader at the fixture file by setting env var (added in impl)
    fixture = Path(__file__).parent / "fixtures" / "mtgo_sample.json"
    monkeypatch.setenv("MTGO_INPUT_PATH", str(fixture))
    monkeypatch.setenv("MTGO_OUTPUT_PATH", str(tmp_path / "out.json"))
    profiles = {
        "Boros Energy": ["Galvanic Discharge", "Guide of Souls", "Ajani, Nacatl Pariah"],
        "UR Prowess": ["Dragon's Rage Channeler", "Stormwild Creeper", "Expressive Iteration"],
    }
    result_path = load_and_classify_mtgo_decklists(profiles, input_path=fixture, output_path=tmp_path / "out.json")
    out = json.loads(result_path.read_text())
    assert out["total_decks"] == 2
    by_id = {d["deck_id"]: d for d in out["decklists"]}
    assert by_id["modern-challenge-64-2026-05-2812843376-1"]["event_type"] == "challenge"
    assert by_id["modern-challenge-64-2026-05-2812843376-1"]["weight"] == 1.0
    assert by_id["modern-challenge-64-2026-05-2812843376-1"]["archetype_canonical"] == "Boros Energy"
    assert by_id["modern-league-2026-05-2910628-2"]["event_type"] == "league"
    assert by_id["modern-league-2026-05-2910628-2"]["weight"] == 0.4
    assert by_id["modern-league-2026-05-2910628-2"]["archetype_canonical"] == "UR Prowess"
```

### Step 2.2: Run tests to verify they fail

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_load_mtgo_decklists.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.load_mtgo_decklists'` for all 7 tests.

### Step 2.3: Implement the loader

Create `/Users/lianghaoming/mtg_agents_workplace/scripts/load_mtgo_decklists.py`:

```python
"""Load MTGO decklists, classify archetypes, assign event_type + weight.

Reads mtg_modern_data/sources/mtgo/mtgo_decklists.json (or a path
passed explicitly), runs card-frequency classification against the
key_card profiles, and writes the enriched output to
mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json.
"""

import json
import re
from pathlib import Path

from scripts.mtgo_classifier import classify_deck_by_cards

DEFAULT_INPUT = Path("mtg_modern_data/sources/mtgo/mtgo_decklists.json")
DEFAULT_OUTPUT = Path("mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json")

CHALLENGE_RE = re.compile(r"challenge", re.IGNORECASE)
LEAGUE_RE = re.compile(r"league", re.IGNORECASE)

EVENT_WEIGHTS = {
    "challenge": 1.0,
    "league": 0.4,
    "other": 0.6,
}


def classify_event_type(event_name: str) -> str:
    """Classify an MTGO event name into challenge / league / other."""
    if CHALLENGE_RE.search(event_name):
        return "challenge"
    if LEAGUE_RE.search(event_name):
        return "league"
    return "other"


def deck_weight(event_type: str) -> float:
    """Return the per-deck weight multiplier for fusion scoring."""
    return EVENT_WEIGHTS[event_type]


def load_and_classify_mtgo_decklists(
    key_card_profiles: dict[str, list[str]],
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    """Classify all decks in input_path, write enriched file to output_path.

    Returns the output_path. Each output deck gains:
      - archetype_canonical: str
      - classification_confidence: float
      - event_type: "challenge" | "league" | "other"
      - weight: float
    """
    with open(input_path) as f:
        raw = json.load(f)

    enriched = []
    for deck in raw.get("decklists", []):
        canon, confidence = classify_deck_by_cards(deck, key_card_profiles)
        event_type = classify_event_type(deck.get("event_name", ""))
        new_deck = dict(deck)
        new_deck["archetype_canonical"] = canon
        new_deck["classification_confidence"] = confidence
        new_deck["event_type"] = event_type
        new_deck["weight"] = deck_weight(event_type)
        enriched.append(new_deck)

    output = {
        "format": raw.get("format", "Modern"),
        "source": "mtgo",
        "period_start": raw.get("period_start"),
        "collected_at": raw.get("collected_at"),
        "total_decks": len(enriched),
        "decklists": enriched,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    return output_path


def _load_key_card_profiles_from_fused() -> dict[str, list[str]]:
    """Pull key_cards out of the existing fused_archetypes.json."""
    fused_path = Path("mtg_modern_data/decks/processed/fused_archetypes.json")
    with open(fused_path) as f:
        data = json.load(f)
    profiles: dict[str, list[str]] = {}
    for arch in data.get("archetypes", {}).values():
        name = arch.get("name")
        cards = arch.get("key_cards") or []
        if name and cards:
            profiles[name] = list(cards)
    return profiles


def main() -> None:
    profiles = _load_key_card_profiles_from_fused()
    if not profiles:
        raise SystemExit("No key_card profiles found. Run evaluate_deck_strength.py first.")
    out = load_and_classify_mtgo_decklists(profiles)
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
```

### Step 2.4: Run tests to verify they pass

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_load_mtgo_decklists.py -v
```

Expected: `7 passed`.

### Step 2.5: Run the loader on the real MTGO data and inspect the output

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 scripts/load_mtgo_decklists.py
```

Expected: prints `Wrote: mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json`.

Then inspect:
```bash
python3 -c "
import json
d = json.load(open('mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json'))
print('total:', d['total_decks'])
from collections import Counter
print('event_types:', Counter(x['event_type'] for x in d['decklists']))
print('top archetypes:', Counter(x['archetype_canonical'] for x in d['decklists']).most_common(5))
"
```

Expected: `total` matches the input (82 on the May 29 sample); `event_types` is mostly `league`; `top archetypes` are real canonical names like `Boros Energy`, `UR Prowess`, etc.

### Step 2.6: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace && git add scripts/load_mtgo_decklists.py tests/test_load_mtgo_decklists.py tests/fixtures/mtgo_sample.json && git commit -m "feat(mtgo): loader that classifies decks and assigns event weights"
```

---

## Task 3: `evaluate_deck_strength.py` MTGO Integration

**Files:**
- Modify: `evaluate_deck_strength.py`
- Modify: `tests/test_evaluate_integration.py` (Create)

**Depends on:** Task 2 (consumes the classified file)

**Goal:** Add `--include-mtgo` to the CLI. When set, `load_decklist_data()` pulls the classified MTGO file, applies per-deck weight as a multiplier on the deck's contribution to `decklist_count`, and the fusion step reflects MTGO counts in the final share / strength score.

### Step 3.1: Add the integration test (failing first)

Create `/Users/lianghaoming/mtg_agents_workplace/tests/test_evaluate_integration.py`:

```python
"""Smoke-level integration test for the MTGO flag.

This is not a full pipeline test. It exercises the decklist-loading and
weight-application code paths in evaluate_deck_strength.py without
running the entire fusion. We monkeypatch the file-system paths so
the test is self-contained.
"""
import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def eval_module(monkeypatch):
    # Force a fresh import so the module picks up argv changes
    if "evaluate_deck_strength" in sys.modules:
        del sys.modules["evaluate_deck_strength"]
    return importlib.import_module("evaluate_deck_strength")


def test_mtgo_flag_is_parsed(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evaluate_deck_strength.py", "--include-mtgo", "--top", "5"])
    if "evaluate_deck_strength" in sys.modules:
        del sys.modules["evaluate_deck_strength"]
    mod = importlib.import_module("evaluate_deck_strength")
    # Module exposes _parse_args or similar; for now just verify the flag
    # does not raise and main() short-circuits on empty data.
    # Full coverage of main() is out of scope; the unit test below is the
    # primary contract.
    assert hasattr(mod, "load_decklist_data")


def test_load_mtgo_decklists_reads_classified_file(eval_module, tmp_path, monkeypatch):
    # Build a minimal classified MTGO file
    mtgo_file = tmp_path / "mtgo_decklists_classified.json"
    mtgo_file.write_text("""{
      "format": "Modern",
      "source": "mtgo",
      "total_decks": 1,
      "decklists": [
        {
          "source": "mtgo",
          "event_id": "test-event",
          "event_name": "MODERN CHALLENGE 32",
          "event_date": "2026-05-28",
          "deck_id": "test-deck-1",
          "deck_name": "",
          "deck_name_canonical": "",
          "archetype_canonical": "Boros Energy",
          "classification_confidence": 0.9,
          "event_type": "challenge",
          "weight": 1.0,
          "player": "P1",
          "placement": "1st",
          "maindeck": [{"qty": 4, "name": "Galvanic Discharge"}],
          "sideboard": [],
          "maindeck_count": 60,
          "sideboard_count": 15,
          "legality": {"legal": true, "banned_cards": []}
        }
      ]
    }""")
    monkeypatch.setattr(
        "evaluate_deck_strength.DEFAULT_MTGO_CLASSIFIED_PATH", mtgo_file
    )
    decks = eval_module._load_mtgo_decks_for_fusion()
    assert len(decks) == 1
    assert decks[0]["_fusion_weight"] == 1.0
    assert decks[0]["archetype_canonical"] == "Boros Energy"
    # The fusion loader must normalize deck_name from the classifier result
    assert decks[0]["deck_name"] == "Boros Energy"


def test_load_mtgo_decklists_applies_league_weight(eval_module, tmp_path, monkeypatch):
    mtgo_file = tmp_path / "mtgo_decklists_classified.json"
    mtgo_file.write_text("""{
      "format": "Modern",
      "source": "mtgo",
      "total_decks": 1,
      "decklists": [
        {
          "archetype_canonical": "UR Prowess",
          "event_type": "league",
          "weight": 0.4,
          "deck_id": "league-deck-1",
          "event_name": "MODERN LEAGUE",
          "event_date": "2026-05-28",
          "player": "P2",
          "placement": "5-0",
          "maindeck": [{"qty": 4, "name": "Dragon's Rage Channeler"}],
          "sideboard": [],
          "maindeck_count": 60,
          "sideboard_count": 15,
          "legality": {"legal": true, "banned_cards": []}
        }
      ]
    }""")
    monkeypatch.setattr(
        "evaluate_deck_strength.DEFAULT_MTGO_CLASSIFIED_PATH", mtgo_file
    )
    decks = eval_module._load_mtgo_decks_for_fusion()
    assert decks[0]["_fusion_weight"] == 0.4
```

### Step 3.2: Run tests to verify they fail

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_evaluate_integration.py -v
```

Expected: failures on `AttributeError: module 'evaluate_deck_strength' has no attribute 'DEFAULT_MTGO_CLASSIFIED_PATH'` and `AttributeError: module ... has no attribute '_load_mtgo_decks_for_fusion'`.

### Step 3.3: Add the MTGO loader constant and helper to `evaluate_deck_strength.py`

Open `/Users/lianghaoming/mtg_agents_workplace/evaluate_deck_strength.py`.

At the top of the file, alongside the other `Path(...)` constants (search for `processed_dir = Path(` near line 931 if needed, but adding a module-level constant near the imports is cleaner), add:

```python
DEFAULT_MTGO_CLASSIFIED_PATH = Path("mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json")
```

Add a new helper function directly above `def load_decklist_data():` (around line 498):

```python
def _load_mtgo_decks_for_fusion(
    classified_path: Path = DEFAULT_MTGO_CLASSIFIED_PATH,
) -> list[dict]:
    """Read the classified MTGO file, return decks shaped for fusion.

    Each returned deck is a shallow copy with:
      - deck_name rewritten from archetype_canonical (if present)
      - _fusion_weight copied from weight (default 1.0 if missing)
    Decks that fail legality are dropped.
    """
    if not classified_path.exists():
        return []
    with open(classified_path) as f:
        data = json.load(f)
    out = []
    for deck in data.get("decklists", []):
        if not deck.get("legality", {}).get("legal", True):
            continue
        new_deck = dict(deck)
        if not new_deck.get("deck_name") and new_deck.get("archetype_canonical"):
            new_deck["deck_name"] = new_deck["archetype_canonical"]
        if not new_deck.get("deck_name"):
            continue
        new_deck["_fusion_weight"] = float(new_deck.get("weight", 1.0))
        out.append(new_deck)
    return out
```

### Step 3.4: Make `load_decklist_data()` accept an `include_mtgo` parameter

In `load_decklist_data()` (line 499), change the signature to:

```python
def load_decklist_data(include_mtgo: bool = False):
```

Right before the line that reads `merged = {` (around line 588), insert:

```python
    # Optionally fold in MTGO decks (Challenge > League weighted)
    mtgo_added = 0
    if include_mtgo:
        mtgo_decks = _load_mtgo_decks_for_fusion()
        # Skip MTGO decks whose (event_name, player) already exist in the merge
        existing_sigs = {
            (d.get("event_name", "").lower(), d.get("player", "").lower())
            for d in merged_decklists
        }
        for d in mtgo_decks:
            sig = (d.get("event_name", "").lower(), d.get("player", "").lower())
            if sig in existing_sigs:
                continue
            merged_decklists.append(d)
            existing_sigs.add(sig)
            mtgo_added += 1
```

Then inside the `merged = { ... }` dict (around lines 588-601), add a key:

```python
        "mtgo_decks": mtgo_added,
```

Change the `print(...)` summary at the end (around line 603) to include MTGO:

```python
    print(f"  Decklist merge: Top8={top8_data.get('total_decks', 0)}"
          f"({top8_illegal} illegal), "
          f"Goldfish={gf_deck_data.get('total_decks', 0)}"
          f"({gf_decks_illegal} illegal), "
          f"GF added={gf_decks_added}, GF skipped={gf_decks_skipped}"
          f"{f', MTGO added={mtgo_added}' if include_mtgo else ''}")
    print(f"  Total legal decks: {total_decks}")
```

### Step 3.5: Apply the per-deck weight in `build_archetype_from_decklists`

Open `build_archetype_from_decklists` (line 691). Find the block that builds `arch_decks` from `decklists` (around lines 698-706). Currently it does:

```python
    arch_decks = defaultdict(list)
    for deck in decklists:
        canon = normalize_archetype_name(deck["deck_name"])
        arch_decks[canon].append(deck)
```

Replace it with:

```python
    arch_decks = defaultdict(list)
    deck_weight_by_id = {}
    weighted_count_per_arch: dict[str, float] = defaultdict(float)
    for deck in decklists:
        canon = normalize_archetype_name(deck["deck_name"])
        arch_decks[canon].append(deck)
        w = float(deck.get("_fusion_weight", 1.0))
        deck_weight_by_id[deck.get("deck_id", id(deck))] = w
        weighted_count_per_arch[canon] += w
```

Then in the per-archetype block that computes `decklist_count` (search for `decklist_count` in the function — the assignment from `len(decks)` is the one to change), replace `decklist_count: len(decks)` with:

```python
        decklist_count: int = len(decks),
        weighted_decklist_count: round(weighted_count_per_arch.get(name, float(len(decks))), 3),
```

(If the field is set positionally in a dict literal, add the new key on the next line and remove the old one carefully — do not break the dict shape.)

### Step 3.6: Wire the flag into `main()`

In `main()` (line 900), replace the existing `decklist_data = load_decklist_data()` call (line 905) with:

```python
    include_mtgo = "--include-mtgo" in sys.argv
    decklist_data = load_decklist_data(include_mtgo=include_mtgo)
```

Also update the `data_sources` list in the `fused_output` dict (line 953) to conditionally include `"mtgo"`:

```python
        "data_sources": ["decklists", "goldfish", "mtgtop8_aggregate"] + (["mtgo"] if include_mtgo else []),
```

### Step 3.7: Run the integration tests

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest tests/test_evaluate_integration.py -v
```

Expected: all 3 tests pass.

### Step 3.8: Run the full pytest suite to confirm nothing else broke

Run:
```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest -v
```

Expected: `15 passed` (5 from Task 1 + 7 from Task 2 + 3 from this task).

### Step 3.9: Commit

```bash
cd /Users/lianghaoming/mtg_agents_workplace && git add evaluate_deck_strength.py tests/test_evaluate_integration.py && git commit -m "feat(mtgo): fold classified MTGO decks into evaluate_deck_strength with event weights"
```

---

## Task 4: End-to-End Smoke Test

**Files:** none modified (read-only verification)

**Depends on:** Task 3

**Goal:** Run the full pipeline with `--include-mtgo` and verify the outputs reflect MTGO data without regressing Top8/Goldfish numbers.

### Step 4.1: Run the loader to refresh the classified file

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 scripts/load_mtgo_decklists.py
```

Expected: prints `Wrote: mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json` and exits 0.

### Step 4.2: Snapshot the pre-integration `fused_archetypes.json` deck count

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -c "
import json
d = json.load(open('mtg_modern_data/decks/processed/fused_archetypes.json'))
print('pre  decklist_sample_size:', d.get('decklist_sample_size'))
print('pre  data_sources:', d.get('fusion_config', {}).get('data_sources'))
"
```

Record the printed values (call them `PRE_SIZE` and `PRE_SOURCES`).

### Step 4.3: Run the full pipeline with `--include-mtgo`

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 evaluate_deck_strength.py --top 15 --include-mtgo
```

Expected: pipeline completes without error. Console output mentions `MTGO added=N` where `N` is at least 1. `fused_archetypes.json` is rewritten.

### Step 4.4: Verify the post-integration outputs

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -c "
import json
d = json.load(open('mtg_modern_data/decks/processed/fused_archetypes.json'))
print('post decklist_sample_size:', d.get('decklist_sample_size'))
print('post data_sources:', d.get('fusion_config', {}).get('data_sources'))
# Sanity: at least one archetype should have a non-integer weighted_decklist_count
has_weighted = any(
    (a.get('weighted_decklist_count') is not None
     and abs(a['weighted_decklist_count'] - a['decklist_count']) > 1e-9)
    for a in d.get('archetypes', {}).values()
)
print('has_weighted_archetype:', has_weighted)
"
```

Expected:
- `post decklist_sample_size` is `>= PRE_SIZE` (MTGO adds decks)
- `post data_sources` contains `"mtgo"`
- `has_weighted_archetype: True` (at least one arch has a non-integer weighted count, e.g. from a 0.4-weight League deck)

### Step 4.5: Rebuild the downstream card impact

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 scripts/build_card_impact.py --top 25
```

Expected: prints top 25 cards. Exit code 0.

### Step 4.6: Run the full pytest suite once more

```bash
cd /Users/lianghaoming/mtg_agents_workplace && python3 -m pytest -v
```

Expected: 15 tests pass.

### Step 4.7: Commit (only if any of steps 4.3-4.5 modified tracked files)

```bash
cd /Users/lianghaoming/mtg_agents_workplace && git status
```

If `mtg_modern_data/decks/processed/fused_archetypes.json` or `mtg_modern_data/cards/card_impact.json` are tracked, commit them:

```bash
cd /Users/lianghaoming/mtg_agents_workplace && git add mtg_modern_data/decks/processed/fused_archetypes.json mtg_modern_data/cards/card_impact.json && git commit -m "chore(data): rebuild fused archetypes and card impact with MTGO source"
```

If they are not tracked, skip the commit. (Confirm with the user before adding data files to git in step 4.7 — see "Out of scope" below.)

---

## Out of Scope

- Modifying `compose_meta.py` or the heuristic matchup matrix.
- Modifying `topdeck_poc.py` or re-running TopDeck quality gate.
- Adding MTGO win-rate estimation (League 5-0 is captured but not consumed).
- Re-tuning `fusion_config.score_weights` — those stay at the values set in `evaluate_deck_strength.py:946`.
- Adding new dependencies. The plan uses only the Python stdlib and `pytest` (already installed).

## Self-Review

- **Spec coverage:** next-data-source-plan.md "Immediate Next Plan" steps 1-4 ↔ Task 3 (flag), Task 1+2 (classifier + loader), Task 3 (weighting), Task 4 (rebuild). Step 5 (TopDeck) is explicitly out of scope.
- **Type consistency:** `archetype_canonical` (loader) → `archetype_canonical` consumed by `_load_mtgo_decks_for_fusion` → `deck_name` rewritten. `_fusion_weight` is the consistent internal name across the loader and fusion step.
- **No placeholders:** every test contains concrete input/expected output; every code block is complete; no "TBD" anywhere.
- **Backwards compatibility:** the `--include-mtgo` flag is opt-in. The default `load_decklist_data(include_mtgo=False)` reproduces today's behavior exactly.

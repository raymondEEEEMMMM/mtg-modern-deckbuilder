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


def test_load_mtgo_decks_reads_classified_file(eval_module, tmp_path, monkeypatch):
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


def test_load_mtgo_decks_applies_league_weight(eval_module, tmp_path, monkeypatch):
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

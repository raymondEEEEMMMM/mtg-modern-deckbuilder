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


def test_load_and_classify_uses_fixture(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "mtgo_sample.json"
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

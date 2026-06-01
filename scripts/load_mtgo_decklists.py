"""Load MTGO decklists, classify archetypes, assign event_type + weight.

Reads mtg_modern_data/sources/mtgo/mtgo_decklists.json (or a path
passed explicitly), runs card-frequency classification against the
key_card profiles, and writes the enriched output to
mtg_modern_data/sources/mtgo/mtgo_decklists_classified.json.
"""

import json
import os
import re
import sys
from pathlib import Path

# Allow `python3 scripts/load_mtgo_decklists.py` to find the scripts package
_BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BASE))

from scripts.mtgo_classifier import classify_deck_by_cards  # noqa: E402

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
    # Allow env-var override for tests / ad-hoc runs
    input_path = Path(os.environ.get("MTGO_INPUT_PATH", input_path))
    output_path = Path(os.environ.get("MTGO_OUTPUT_PATH", output_path))

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
    """Pull key_cards out of the existing fused_archetypes.json.

    Note: in this codebase `archetypes` is a JSON list, not a dict.
    """
    fused_path = Path("mtg_modern_data/decks/processed/fused_archetypes.json")
    with open(fused_path) as f:
        data = json.load(f)
    profiles: dict[str, list[str]] = {}
    for arch in data.get("archetypes", []):
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

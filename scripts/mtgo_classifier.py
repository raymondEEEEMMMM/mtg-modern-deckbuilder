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

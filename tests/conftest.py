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
            {"qty": 4, "name": "Ocelot Pride"},
            # ... truncated for fixture; real decks have 60 cards
        ],
        "sideboard": [{"qty": 1, "name": "Blood Moon"}],
        "maindeck_count": 60,
        "sideboard_count": 15,
        "legality": {"legal": True, "banned_cards": []},
    }

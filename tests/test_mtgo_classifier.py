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

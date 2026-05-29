#!/usr/bin/env python3
"""
TopDeck.gg API PoC for Modern round-level matchup data.

Requires:
  TOPDECK_API_KEY=... python3 scripts/topdeck_poc.py

Outputs:
  mtg_modern_data/sources/topdeck/raw/topdeck_modern_<period>.json
  mtg_modern_data/sources/topdeck/topdeck_quality_report.json
  mtg_modern_data/sources/topdeck/real_matchup_matrix_trial.json (only if quality gate passes)
"""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "mtg_modern_data"
FUSED_PATH = DATA_DIR / "decks" / "processed" / "fused_archetypes.json"
META_PATH = DATA_DIR / "ban_list" / "meta.json"
OUTPUT_DIR = DATA_DIR / "sources" / "topdeck"
RAW_DIR = OUTPUT_DIR / "raw"
REPORT_PATH = OUTPUT_DIR / "topdeck_quality_report.json"
TRIAL_MATRIX_PATH = OUTPUT_DIR / "real_matchup_matrix_trial.json"

API_URL = "https://topdeck.gg/api/v2/tournaments"

QUALITY_GATE = {
    "min_completed_events": 5,
    "min_classified_matches": 100,
    "min_classification_coverage": 0.70,
    "min_top_pair_sample_count": 3,
}


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def period_start() -> str:
    meta = load_json(META_PATH)
    return meta.get("changes_history", [{}])[-1].get("effective_date", "2026-05-18")


def unix_seconds(date_text: str) -> int:
    dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def normalize_card_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()


def build_archetype_profiles() -> dict:
    fused = load_json(FUSED_PATH)
    profiles = {}
    for arch in fused.get("archetypes", []):
        name = arch["name"]
        cards = set()
        for card in arch.get("key_cards", []):
            cards.add(normalize_card_name(card))
        for item in arch.get("key_cards_detail") or []:
            if item.get("ubiquity", 0) >= 0.4:
                cards.add(normalize_card_name(item.get("name", "")))
        if cards:
            profiles[name] = {
                "cards": cards,
                "tier": arch.get("tier", "Tier 4"),
                "share": arch.get("fused_metagame_share", 0),
            }
    return profiles


def extract_cards_from_deck_obj(deck_obj) -> Counter:
    """Extract flexible card quantities from TopDeck deckObj/decklist structures."""
    cards = Counter()

    def add_card(item, weight=1.0):
        if isinstance(item, str):
            name = item
            qty = 1
        elif isinstance(item, dict):
            name = (
                item.get("name")
                or item.get("card")
                or item.get("cardName")
                or item.get("card_name")
                or item.get("title")
            )
            qty = item.get("qty", item.get("quantity", item.get("count", 1)))
        else:
            return
        name = normalize_card_name(name)
        if not name:
            return
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            qty = 1
        cards[name] += qty * weight

    def walk(obj, section_weight=1.0):
        if isinstance(obj, list):
            for item in obj:
                add_card(item, section_weight)
            return
        if not isinstance(obj, dict):
            return
        for key, value in obj.items():
            lower = str(key).lower()
            if lower == "metadata":
                continue
            weight = 0.35 if "side" in lower else section_weight
            if isinstance(value, list):
                for item in value:
                    add_card(item, weight)
            elif isinstance(value, dict):
                # TopDeck deckObj commonly stores sections as:
                # {"Mainboard": {"Card Name": {"count": 4, ...}}}
                if value and all(isinstance(v, dict) and "count" in v for v in value.values()):
                    for card_name, card_data in value.items():
                        add_card({"name": card_name, "count": card_data.get("count", 1)}, weight)
                elif "count" in value and not any(k.lower() in {"mainboard", "sideboard", "metadata"} for k in value):
                    add_card({"name": key, "count": value.get("count", 1)}, section_weight)
                else:
                    walk(value, weight)

    walk(deck_obj)
    return cards


def classify_deck(card_counts: Counter, profiles: dict) -> dict:
    if not card_counts:
        return {"archetype": None, "confidence": 0, "method": "no_decklist"}

    deck_cards = set(card_counts)
    best = None
    for archetype, profile in profiles.items():
        core = profile["cards"]
        if not core:
            continue
        overlap = deck_cards & core
        coverage = len(overlap) / len(core)
        precision = len(overlap) / max(1, min(len(deck_cards), len(core) + 10))
        tier_bonus = 0.05 if profile.get("tier") in {"Tier 1", "Tier 2"} else 0
        score = min(1.0, 0.75 * coverage + 0.25 * precision + tier_bonus)
        row = {
            "archetype": archetype,
            "confidence": round(score, 4),
            "matched_cards": sorted(overlap),
            "core_size": len(core),
        }
        if not best or row["confidence"] > best["confidence"]:
            best = row

    if not best or best["confidence"] < 0.35:
        return {"archetype": None, "confidence": best["confidence"] if best else 0, "method": "low_confidence"}
    best["method"] = "card_profile"
    return best


def request_topdeck(api_key: str, payload: dict) -> list:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "User-Agent": "mtg-modern-workflow/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TopDeck API HTTP {exc.code}: {detail}") from exc


def player_key(player: dict) -> str:
    return str(player.get("id") or player.get("name") or "").strip()


def player_deck_obj(player: dict):
    return player.get("deckObj") or player.get("decklist") or player.get("deck")


def analyze_tournaments(tournaments: list, profiles: dict, confidence_threshold: float) -> dict:
    player_classes = {}
    player_decklist_present = set()
    player_seen = set()
    match_records = []
    event_summaries = []

    for event in tournaments:
        tid = event.get("TID") or event.get("tid") or event.get("id")
        event_name = event.get("name", "")
        standings = event.get("standings", []) or []
        rounds = event.get("rounds", []) or []
        status = event.get("status", "")

        event_players = set()
        event_decklists = set()
        event_classified = set()

        for row in standings:
            key = player_key(row)
            if not key:
                continue
            player_seen.add(key)
            event_players.add(key)
            deck_obj = player_deck_obj(row)
            if deck_obj:
                player_decklist_present.add(key)
                event_decklists.add(key)
                card_counts = extract_cards_from_deck_obj(deck_obj)
                classification = classify_deck(card_counts, profiles)
                if classification.get("confidence", 0) >= confidence_threshold and classification.get("archetype"):
                    event_classified.add(key)
                player_classes[key] = {
                    "event_id": tid,
                    "player": row.get("name", key),
                    "classification": classification,
                }

        for rnd in rounds:
            round_name = rnd.get("round")
            tables = rnd.get("tables", []) or []
            for table in tables:
                players = table.get("players", []) or []
                if len(players) != 2:
                    continue
                p1_key = player_key(players[0])
                p2_key = player_key(players[1])
                if not p1_key or not p2_key:
                    continue
                player_seen.update([p1_key, p2_key])
                c1 = player_classes.get(p1_key, {}).get("classification", {})
                c2 = player_classes.get(p2_key, {}).get("classification", {})
                a1 = c1.get("archetype")
                a2 = c2.get("archetype")
                winner_id = table.get("winner_id")
                winner = table.get("winner")
                status_text = table.get("status")

                if a1 and a2:
                    result = "draw"
                    if winner_id and winner_id == p1_key:
                        result = "p1"
                    elif winner_id and winner_id == p2_key:
                        result = "p2"
                    elif winner and winner == players[0].get("name"):
                        result = "p1"
                    elif winner and winner == players[1].get("name"):
                        result = "p2"

                    match_records.append({
                        "event_id": tid,
                        "event_name": event_name,
                        "round": round_name,
                        "table": table.get("table"),
                        "player1": players[0].get("name"),
                        "player2": players[1].get("name"),
                        "archetype1": a1,
                        "archetype2": a2,
                        "winner": result,
                        "status": status_text,
                    })

        event_summaries.append({
            "event_id": tid,
            "name": event_name,
            "status": status,
            "standings_count": len(standings),
            "round_count": len(rounds),
            "players_seen": len(event_players),
            "players_with_decklist": len(event_decklists),
            "players_classified": len(event_classified),
        })

    decklist_coverage = len(player_decklist_present) / len(player_seen) if player_seen else 0
    classification_coverage = len({
        key for key, row in player_classes.items()
        if row["classification"].get("archetype")
        and row["classification"].get("confidence", 0) >= confidence_threshold
    }) / len(player_seen) if player_seen else 0

    return {
        "event_summaries": event_summaries,
        "player_count": len(player_seen),
        "players_with_decklist": len(player_decklist_present),
        "decklist_coverage": round(decklist_coverage, 4),
        "classification_coverage": round(classification_coverage, 4),
        "match_records": match_records,
        "player_classes": player_classes,
    }


def build_trial_matrix(match_records: list) -> dict:
    pair_stats = defaultdict(lambda: {"wins1": 0, "wins2": 0, "draws": 0, "games": 0})
    for match in match_records:
        a1 = match["archetype1"]
        a2 = match["archetype2"]
        key = tuple(sorted([a1, a2]))
        flip = (a1, a2) != key
        pair_stats[key]["games"] += 1
        winner = match["winner"]
        if winner == "draw":
            pair_stats[key]["draws"] += 1
        elif (winner == "p1" and not flip) or (winner == "p2" and flip):
            pair_stats[key]["wins1"] += 1
        elif winner in {"p1", "p2"}:
            pair_stats[key]["wins2"] += 1

    return {
        f"{a1}|{a2}": stats
        for (a1, a2), stats in sorted(pair_stats.items())
    }


def quality_report(tournaments: list, analysis: dict, trial_stats: dict, payload: dict) -> dict:
    pair_sample_counts = Counter()
    for key, stats in trial_stats.items():
        pair_sample_counts[key] = stats["games"]

    top_pair_sample_count = max(pair_sample_counts.values()) if pair_sample_counts else 0
    completed_events = len(tournaments)
    classified_match_count = len(analysis["match_records"])
    gate = {
        "completed_events": completed_events >= QUALITY_GATE["min_completed_events"],
        "classified_match_count": classified_match_count >= QUALITY_GATE["min_classified_matches"],
        "classification_coverage": analysis["classification_coverage"] >= QUALITY_GATE["min_classification_coverage"],
        "top_pair_sample_count": top_pair_sample_count >= QUALITY_GATE["min_top_pair_sample_count"],
    }
    passed = all(gate.values())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "TopDeck.gg API",
        "attribution_required": "Data provided by TopDeck.gg: https://topdeck.gg",
        "request_payload": payload,
        "quality_gate": QUALITY_GATE,
        "quality_gate_results": gate,
        "passed": passed,
        "summary": {
            "completed_events": completed_events,
            "player_count": analysis["player_count"],
            "players_with_decklist": analysis["players_with_decklist"],
            "decklist_coverage": analysis["decklist_coverage"],
            "classification_coverage": analysis["classification_coverage"],
            "classified_match_count": classified_match_count,
            "archetype_pair_count": len(trial_stats),
            "top_pair_sample_count": top_pair_sample_count,
        },
        "top_pairs": [
            {"pair": pair, "games": count}
            for pair, count in pair_sample_counts.most_common(20)
        ],
        "events": analysis["event_summaries"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TopDeck.gg Modern data source PoC")
    parser.add_argument("--last", type=int, default=None, help="Days back from today; overrides period start")
    parser.add_argument("--participant-min", type=int, default=8)
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--dry-run", action="store_true", help="Write request payload only; do not call API")
    args = parser.parse_args()

    api_key = os.environ.get("TOPDECK_API_KEY", "").strip()
    ps = period_start()
    now_ts = int(time.time())
    payload = {
        "game": "Magic: The Gathering",
        "format": "Modern",
        "participantMin": args.participant_min,
        "columns": ["name", "id", "decklist", "wins", "draws", "losses"],
        "rounds": True,
        "tables": ["table", "players", "winner", "status"],
        "players": ["name", "id", "decklist"],
    }
    if args.last:
        payload["last"] = args.last
    else:
        payload["start"] = unix_seconds(ps)
        payload["end"] = now_ts

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = OUTPUT_DIR / "topdeck_request_payload.json"
    save_json(payload, payload_path)

    if args.dry_run:
        print(f"Dry run wrote {payload_path}")
        return

    if not api_key:
        raise SystemExit(
            "TOPDECK_API_KEY is required. Create a free key from TopDeck.gg "
            "and run: TOPDECK_API_KEY=... python3 scripts/topdeck_poc.py"
        )

    tournaments = request_topdeck(api_key, payload)
    if not isinstance(tournaments, list):
        raise SystemExit(f"Unexpected TopDeck response shape: {type(tournaments).__name__}")

    raw_path = RAW_DIR / f"topdeck_modern_{ps}.json"
    save_json({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period_start": ps,
        "payload": payload,
        "tournaments": tournaments,
    }, raw_path)

    profiles = build_archetype_profiles()
    analysis = analyze_tournaments(tournaments, profiles, args.confidence)
    trial_stats = build_trial_matrix(analysis["match_records"])
    report = quality_report(tournaments, analysis, trial_stats, payload)
    save_json(report, REPORT_PATH)

    if report["passed"]:
        save_json({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "TopDeck.gg API",
            "quality_report": str(REPORT_PATH.relative_to(BASE)),
            "matchup_stats": trial_stats,
            "raw_match_count": len(analysis["match_records"]),
        }, TRIAL_MATRIX_PATH)

    print(f"Raw: {raw_path}")
    print(f"Report: {REPORT_PATH}")
    print(f"Passed quality gate: {report['passed']}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

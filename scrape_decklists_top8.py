#!/usr/bin/env python3
"""
MTGTop8 Full Decklist Scraper

Scrapes complete 75-card decklists from MTGTop8 Modern events.
Validates each deck against the current Modern banlist.

Usage:
  python3 scrape_decklists_top8.py [--max-events N] [--skip-existing]
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("mtg_modern_data/decks/raw/decklists")
BANLIST_FILE = Path("mtg_modern_data/ban_list/current.json")
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
EVENTS_FILE = Path("mtg_modern_data/decks/raw/2026-05-27_mtgtop8.json")

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

# MTGTop8 event page URLs
MODERN_FORMAT_URL = "https://www.mtgtop8.com/format?f=MO&meta=221"

# Category headers to skip when parsing decklists
# MTGTop8 format: "LANDS (23)", "CREATURES (22)", "INSTANTS and SORC. (16)", etc.
CATEGORY_HEADERS = re.compile(
    r"^(LANDS|CREATURES|INSTANTS and SORC\.?|INSTANTS|SORC\.?|OTHER SPELLS|"
    r"ARTIFACTS|ENCHANTMENTS|PLANESWALKERS|SPELLS)"
    r"\s*\(\d+\)?$",
    re.IGNORECASE,
)

# Archetype name normalization (Top8 deck_name → canonical)
# Full mapping in mtg_modern_data/decks/archetype_name_map.json
ARCHETYPE_NORMALIZE = {
    "UrzaTron": "UW Tron", "Urzatron": "UW Tron",
    "Uw Control": "UW Control", "Ub Mill": "UB Mill",
    "Izzet Affinity": "Affinity", "Pinnacle Affinity": "Affinity",
    "Izzet Prowess": "UR Prowess", "UR Cutter Prowess": "UR Prowess",
    "Ur Cutter Prowess": "UR Prowess", "Russian Prowess": "UR Prowess",
    "Prowess": "UR Prowess",
    "Landless Belcher": "Landless", "Goblins Combo": "Landless",
    "Boros Aggro": "Boros Energy", "Jeskai Energy": "Boros Energy",
    "Domain Rhinos": "Crashing Footfalls", "Temur Rhinos": "Crashing Footfalls",
    "Simic Birthing Ritual": "Birthing Ritual",
    "Selesnya Aggro Birthing Ritual": "Birthing Ritual", "Simic Ritual": "Birthing Ritual",
    "Mono Green Aggro": "Mono-G Aggro",
    "Mono": "Mono-Black Midrange",
    "Mono Black Aggro Necrodominance": "Mono-Black Midrange",
    "Azorius Blink": "Blink", "Orzhov Blink": "Blink", "Esper Blink": "Blink",
    "Mardu Blink": "Blink", "Domain Blink": "Blink", "Esper Eugè": "Blink",
    "Frog Legs": "Frog Combo",
    "Grixis Death Shadow": "Death's Shadow",
    "Samwise Combo": "Yawgmoth",
    "Burn": "Red Deck Wins",
    "Chord Toolbox": "Creatures Toolbox",
    "Scepter Chant": "UW Control",
    "Soultrader": "Sacrifice Combo",
}


def normalize_archetype_name(name: str) -> str:
    """Map raw deck_name to canonical archetype."""
    return ARCHETYPE_NORMALIZE.get(name, name)


def load_banlist() -> set:
    if not BANLIST_FILE.exists():
        print("Warning: No banlist found, skipping legality check")
        return set()
    with open(BANLIST_FILE) as f:
        return set(json.load(f).get("banned", []))


def check_legality(maindeck: list, sideboard: list, banlist: set) -> dict:
    """Check deck for banned cards. Returns legality report."""
    banned_cards = []
    all_cards = maindeck + sideboard
    for card in all_cards:
        if card["name"] in banlist:
            banned_cards.append({"name": card["name"], "qty": card["qty"], "zone": "maindeck" if card in maindeck else "sideboard"})

    return {
        "legal": len(banned_cards) == 0,
        "banned_cards": banned_cards,
    }


def parse_decklist_from_text(text: str) -> tuple:
    """Parse decklist from page text. Returns (maindeck, sideboard)."""
    md_idx = text.find("MD ")
    if md_idx < 0:
        return [], []

    deck_section = text[md_idx:]
    lines = deck_section.split("\n")

    maindeck = []
    sideboard = []
    in_sb = False

    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue

        if trimmed == "SIDEBOARD":
            in_sb = True
            continue

        # Stop markers
        if any(trimmed.startswith(s) for s in ["Switch to", "Explain!", "Export", "MTGO", ".dec"]):
            continue

        # Parse card lines: "4 Ragavan, Nimble Pilferer"
        card_match = re.match(r"^(\d+)\s+(.+)$", trimmed)
        if card_match:
            qty = int(card_match.group(1))
            name = card_match.group(2).strip()
            # Skip category headers
            if CATEGORY_HEADERS.match(name):
                continue
            entry = {"qty": qty, "name": name}
            if in_sb:
                sideboard.append(entry)
            else:
                maindeck.append(entry)

    return maindeck, sideboard


# ─── Playwright Scraper ──────────────────────────────────────────────────────

def get_event_links(page) -> list:
    """Get all Modern event links from the format page."""
    page.goto(MODERN_FORMAT_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)

    # Also get page 2
    events = page.evaluate("""() => {
        const links = document.querySelectorAll('a[href*="event?e="]');
        const seen = new Set();
        const result = [];
        for (const a of links) {
            const href = a.getAttribute('href');
            const match = href.match(/e=(\\d+)/);
            if (match && !seen.has(match[1])) {
                seen.add(match[1]);
                const fullUrl = href.startsWith('http') ? href : 'https://www.mtgtop8.com/' + href.replace(/^\\//, '');
                result.push({
                    event_id: match[1],
                    url: fullUrl,
                    text: a.textContent.trim().substring(0, 80)
                });
            }
        }
        return result;
    }""")

    print(f"Found {len(events)} event links")
    return events


def get_deck_links_from_event(page, event_url: str) -> list:
    """Get all deck links from an event page."""
    page.goto(event_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)

    # Get event metadata and deck links
    result = page.evaluate("""() => {
        const text = document.body.innerText;

        // Parse event name from the page title or first heading
        const titleEl = document.querySelector('td.w_title');
        const eventName = titleEl ? titleEl.textContent.trim() : '';

        // Parse date
        const dateMatch = text.match(/(\\d{2})\\/(\\d{2})\\/(\\d{2})/);
        const date = dateMatch ? dateMatch[0] : '';

        // Parse player count
        const playerMatch = text.match(/(\\d+)\\s*players/);
        const playerCount = playerMatch ? parseInt(playerMatch[1]) : 0;

        // Get deck links - look for links with d= parameter
        const links = document.querySelectorAll('a[href*="d="]');
        const seen = new Set();
        const deckLinks = [];

        for (const a of links) {
            const href = a.getAttribute('href');
            if (!href) continue;
            const match = href.match(/d=(\\d+)/);
            if (!match) continue;

            const deckId = match[1];
            if (seen.has(deckId)) continue;
            seen.add(deckId);

            // Get archetype name - may be in the link itself or in a sibling/parent
            let archetype = a.textContent.trim();
            // If the link text is just an arrow, look for the archetype name in the parent row
            if (!archetype || archetype === '→' || archetype.length < 2) {
                const row = a.closest('tr, div, li');
                if (row) {
                    const allText = row.textContent.trim();
                    // Extract archetype name from row text like "Simic Ritual Ardonas →"
                    const nameMatch = allText.match(/^([\\w\\s/'.-]+?)(?:\\s+\\S+\\s*→?$|\\s*$)/);
                    if (nameMatch) archetype = nameMatch[1].trim();
                }
            }

            const fullUrl = href.startsWith('http') ? href : 'https://www.mtgtop8.com/event' + href.replace(/^event/, '');
            deckLinks.push({
                deck_id: deckId,
                url: fullUrl,
                archetype: archetype || 'Unknown'
            });
        }

        return {
            event_info: {
                name: eventName,
                date: date,
                player_count: playerCount,
            },
            deck_links: deckLinks
        };
    }""")

    return result


def scrape_decklist(page, deck_url: str) -> dict:
    """Scrape a full decklist from a deck page."""
    page.goto(deck_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(0.5)

    result = page.evaluate("""() => {
        const text = document.body.innerText;

        // Extract deck name and player
        const titleMatch = document.title.match(/^(.+?)\\s*-\\s*(.+?)\\s*@/);

        // Find MD section
        const mdIdx = text.indexOf('MD ');
        if (mdIdx < 0) return {error: 'No MD section found'};

        const deckSection = text.substring(mdIdx);
        const lines = deckSection.split('\\n');

        const maindeck = [];
        const sideboard = [];
        let inSB = false;

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            if (trimmed === 'SIDEBOARD') {
                inSB = true;
                continue;
            }
            if (['Switch to', 'Explain!', 'Export', 'MTGO', '.dec', 'Boros Aggro decks', ' decks'].some(s => trimmed.startsWith(s))) continue;

            const cardMatch = trimmed.match(/^(\\d+)\\s+(.+)$/);
            if (cardMatch) {
                const qty = parseInt(cardMatch[1]);
                const name = cardMatch[2].trim();
                // Skip category headers
                // Skip category headers like "LANDS", "CREATURES", "INSTANTS and SORC.", etc.
                const catHeaders = ['LANDS','CREATURES','INSTANTS and SORC.','INSTANTS and SORC','SORC.','SORC','OTHER SPELLS','ARTIFACTS','ENCHANTMENTS','PLANESWALKERS','SPELLS'];
                if (catHeaders.includes(name)) continue;
                // Also skip "LANDS (23)" format
                if (/^(LANDS|CREATURES|INSTANTS|SORC|OTHER SPELLS|ARTIFACTS|ENCHANTMENTS|PLANESWALKERS|SPELLS)\\s*\\(\\d+\\)$/i.test(name)) continue;
                const entry = {qty, name};
                if (inSB) sideboard.push(entry);
                else maindeck.push(entry);
            }
        }

        return {
            deck_name: titleMatch ? titleMatch[1] : '',
            player: titleMatch ? titleMatch[2] : '',
            maindeck,
            sideboard,
            maindeck_count: maindeck.reduce((s, c) => s + c.qty, 0),
            sideboard_count: sideboard.reduce((s, c) => s + c.qty, 0),
        };
    }""")

    return result


def main():
    from playwright.sync_api import sync_playwright

    max_events = int(sys.argv[sys.argv.index("--max-events") + 1]) if "--max-events" in sys.argv else 999
    skip_existing = "--skip-existing" in sys.argv

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} cards")
    print(f"Period start: {PERIOD_START}")

    all_decklists = []
    legality_report = {"legal": 0, "illegal": 0, "illegal_decks": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Step 1: Get event links
        print("\n=== Step 1: Getting event links ===")
        events = get_event_links(page)

        # Filter by date (rough - we'll check more precisely after loading)
        # MTGTop8 dates are DD/MM/YY format
        recent_events = []
        for ev in events:
            # We'll check dates after loading event pages
            recent_events.append(ev)

        print(f"Events to scrape: {min(len(recent_events), max_events)}")

        # Step 2: For each event, get deck links and scrape decklists
        print("\n=== Step 2: Scraping decklists ===")
        scraped_count = 0
        error_count = 0

        for i, event in enumerate(recent_events[:max_events]):
            print(f"\n[{i+1}/{min(len(recent_events), max_events)}] Event: {event['text']} (id={event['event_id']})")

            try:
                event_data = get_deck_links_from_event(page, event["url"])
                event_info = event_data["event_info"]
                deck_links = event_data["deck_links"]

                print(f"  Event info: {event_info}")
                print(f"  Decks found: {len(deck_links)}")

                # Skip events before period start, and normalize date to ISO format
                event_date_iso = ""
                if event_info.get("date"):
                    try:
                        parts = event_info["date"].split("/")
                        event_date_iso = f"20{parts[2]}-{parts[1]}-{parts[0]}"
                        if event_date_iso < PERIOD_START:
                            print(f"  Skipping (before {PERIOD_START})")
                            continue
                    except (IndexError, ValueError):
                        event_date_iso = event_info["date"]

                for j, deck_link in enumerate(deck_links):
                    try:
                        print(f"  [{j+1}/{len(deck_links)}] Scraping {deck_link['archetype']}...", end=" ")
                        deck_data = scrape_decklist(page, deck_link["url"])

                        if "error" in deck_data:
                            print(f"ERROR: {deck_data['error']}")
                            error_count += 1
                            continue

                        # Build decklist entry
                        raw_deck_name = deck_data.get("deck_name", deck_link["archetype"])
                        entry = {
                            "source": "mtgtop8",
                            "event_id": event["event_id"],
                            "event_name": event_info.get("name", event["text"]),
                            "event_date": event_date_iso,
                            "deck_id": deck_link["deck_id"],
                            "deck_name": raw_deck_name,
                            "deck_name_canonical": normalize_archetype_name(raw_deck_name),
                            "player": deck_data.get("player", ""),
                            "maindeck": deck_data["maindeck"],
                            "sideboard": deck_data["sideboard"],
                            "maindeck_count": deck_data["maindeck_count"],
                            "sideboard_count": deck_data["sideboard_count"],
                        }

                        # Legality check
                        legality = check_legality(deck_data["maindeck"], deck_data["sideboard"], banlist)
                        entry["legality"] = legality

                        if legality["legal"]:
                            legality_report["legal"] += 1
                            print(f"OK ({entry['maindeck_count']}+{entry['sideboard_count']})")
                        else:
                            legality_report["illegal"] += 1
                            banned_names = [c["name"] for c in legality["banned_cards"]]
                            legality_report["illegal_decks"].append({
                                "deck": f"{entry['deck_name']} ({entry['player']})",
                                "event": event_info.get("name", ""),
                                "banned_cards": banned_names,
                            })
                            print(f"ILLEGAL: {banned_names}")

                        all_decklists.append(entry)
                        scraped_count += 1

                    except Exception as e:
                        print(f"ERROR: {e}")
                        error_count += 1

                    # Rate limit
                    time.sleep(0.3)

            except Exception as e:
                print(f"  Event error: {e}")
                error_count += 1
                continue

            # Rate limit between events
            time.sleep(1)

        browser.close()

    # Step 3: Save results
    print(f"\n=== Results ===")
    print(f"Total decklists scraped: {scraped_count}")
    print(f"Errors: {error_count}")
    print(f"Legal decks: {legality_report['legal']}")
    print(f"Illegal decks: {legality_report['illegal']}")

    if legality_report["illegal_decks"]:
        print(f"\nIllegal deck details:")
        for d in legality_report["illegal_decks"]:
            print(f"  ⚠ {d['deck']} [{d['event']}]: {d['banned_cards']}")

    # Save full decklist data
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

    output_file = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_top8_decklists.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved: {output_file}")


if __name__ == "__main__":
    main()

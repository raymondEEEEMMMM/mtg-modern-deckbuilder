#!/usr/bin/env python3
"""
MTGGoldfish Full Decklist Scraper

Scrapes complete 75-card decklists from MTGGoldfish Modern tournaments.
Uses "Expand" on tournament pages to extract decklists inline,
avoiding Cloudflare blocks on individual deck pages.

Strategy:
  - MTGTop8 decklists are the primary source (already collected)
  - Goldfish supplements with archetypes/decklists NOT covered by Top8
  - Uses tournament search to find events in the current period
  - Expands each deck row to get full maindeck + sideboard

Features:
  - Incremental save after each tournament (progress preserved on crash)
  - Resume mode (--resume) to skip already-scraped tournaments
  - Cloudflare retry with exponential backoff
  - Overlap detection with Top8 data (--skip-top8-overlap)

Usage:
  python3 scrape_decklists_goldfish.py [--max-tournaments N] [--skip-top8-overlap] [--resume]

Requires: playwright (pip install playwright && python -m playwright install chromium)
Note: Must run in NON-headless mode to pass Cloudflare.
"""

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("mtg_modern_data/decks/raw/decklists")
BANLIST_FILE = Path("mtg_modern_data/ban_list/current.json")
TOP8_DECKLISTS_FILE = Path("mtg_modern_data/decks/raw/decklists/2026-05-27_top8_decklists.json")

# Read period_start from meta.json if available
META_FILE = Path("mtg_modern_data/ban_list/meta.json")
PERIOD_START = "2026-05-18"
if META_FILE.exists():
    try:
        with open(META_FILE) as _f:
            _meta = json.load(_f)
        if "changes_history" in _meta and _meta["changes_history"]:
            PERIOD_START = _meta["changes_history"][-1].get("effective_date", PERIOD_START)
    except Exception:
        pass

GOLDFISH_TOURNAMENT_SEARCH_URL = (
    "https://www.mtggoldfish.com/tournament_searches/create?"
    "tournament_search%5Bname%5D=&tournament_search%5Bformat%5D=modern"
    "&tournament_search%5Bdate_range%5D={start}+-+{end}&commit=Search"
)

# ─── Archetype Normalization ─────────────────────────────────────────────────

GOLDFISH_TO_CANONICAL = {
    "Belcher": "Landless",
    "Azorius GenericBlink": "Blink",
    "Esper GenericBlink": "Blink",
    "Mardu GenericBlink": "Blink",
    "Jeskai Blink": "Blink",
    "Domain Zoo": "4/5c Aggro",
    "4c Energy": "Boros Energy",
    "Gruul Basking Broodscale Combo": "Broodscale Bloodchief",
    "Mono-Green Basking Broodscale Combo": "Broodscale Bloodchief",
    "Basking Broodscale Combo": "Broodscale Bloodchief",
    "Izzet Prowess": "UR Prowess",
    "Izzet Affinity": "Affinity",
    "Neobrand": "Allosaurus Combo",
    "Boros Burn": "Red Deck Wins",
    "Indomitable Creativity": "Creativity",
    "Domain Rhinos": "Crashing Footfalls",
    "Temur Rhinos": "Crashing Footfalls",
    "WR": "Red Deck Wins",
    "RG": "Red Deck Wins",
    "BR": "Red Deck Wins",
    "G": "Mono-G Aggro",
    "WU": "UW Control",
    "Mardu Energy": "Mardu Aggro",
    "Esper Murktide": "Death's Shadow",
    "Amulet Titan": "Amulet Titan",
    "Merfolk": "Merfolk",
    "Izzet": "UR Prowess",
    "Eldrazi": "Eldrazi Ramp",
    "Temur": "4/5c Aggro",
    "Temur Midrange": "4/5c Aggro",
    "Yawgmoth Combo": "Yawgmoth",
    "Living End": "Living End",
    "Affinity": "Affinity",
    "UW Control": "UW Control",
    "Ruby Storm": "Ruby Storm",
    "Dimir Control": "Dimir Control",
    "Dimir Midrange": "Dimir Midrange",
    "Sultai Midrange": "Sultai Midrange",
    "Grixis Reanimator": "Grixis Reanimator",
    "Eldrazi Tron": "Eldrazi Tron",
    "Eldrazi Ramp": "Eldrazi Ramp",
    "Goryo's Vengeance": "Goryo's Vengeance",
    "Dredge": "Dredge",
    "Hammer Time": "Hammer Time",
    "Creativity": "Creativity",
    "Tron": "UW Tron",
    "Amulet": "Amulet Titan",
    "Prowess": "UR Prowess",
    "Burn": "Red Deck Wins",
    "Mill": "UB Mill",
    "Shadow": "Death's Shadow",
    "Underworld Cookbook": "The Underworld Cookbook",
    "Cascade Crash": "Cascade Crash",
    "Boros Ponza": "Boros Ponza",
    "Reanimator": "Reanimator",
    "Instant Reanimator": "Instant Reanimator",
    "Death's Shadow": "Death's Shadow",
    "Broodscale Combo": "Broodscale Bloodchief",
    "Mono-Black Midrange": "Mono-Black Midrange",
    "Mono-Green Stompy": "Mono-G Aggro",
}


def normalize_archetype(name: str) -> str:
    return GOLDFISH_TO_CANONICAL.get(name, name)


# ─── Decklist Parsing ────────────────────────────────────────────────────────

def parse_deck_from_data_attrs(page, deck_id: str) -> dict:
    """Parse decklist using data-card-name attributes (most reliable)."""
    cards = page.evaluate("""(deckId) => {
        const container = document.querySelector(`[id*="deck-${deckId}-tab"]`);
        if (!container) return {maindeck: [], sideboard: []};
        
        const table = container.querySelector('.deck-view-deck-table');
        if (!table) return {maindeck: [], sideboard: []};
        
        const maindeck = [];
        const sideboard = [];
        let inSideboard = false;
        
        const rows = table.querySelectorAll('tr');
        for (const row of rows) {
            const header = row.querySelector('th');
            if (header && header.innerText.trim().startsWith('Sideboard')) {
                inSideboard = true;
                continue;
            }
            if (header) continue;
            
            const cardName = row.getAttribute('data-card-name');
            if (cardName) {
                const qtyCell = row.querySelector('td');
                const qty = qtyCell ? parseInt(qtyCell.innerText.trim()) || 1 : 1;
                if (inSideboard) {
                    sideboard.push({qty, name: cardName});
                } else {
                    maindeck.push({qty, name: cardName});
                }
            }
        }
        return {maindeck, sideboard};
    }""", deck_id)
    return cards


def parse_deck_from_text(page, deck_id: str) -> dict:
    """Fallback: parse decklist from text content."""
    text = page.evaluate("""(deckId) => {
        const container = document.querySelector(`[id*="deck-${deckId}-tab"]`);
        if (!container) return '';
        const table = container.querySelector('.deck-view-deck-table');
        return table ? table.innerText : '';
    }""", deck_id)

    if not text:
        return {"maindeck": [], "sideboard": []}

    maindeck, sideboard = [], []
    in_sb = False
    for line in text.split("\n"):
        line = line.strip().replace("\xa0", " ")
        if not line:
            continue
        if line.startswith("Sideboard"):
            in_sb = True
            continue
        if re.match(r"^(Creatures|Spells|Lands|Sorceries|Instants|Enchantments|Planeswalkers|Artifacts)\s*\(", line):
            continue
        if any(k in line for k in ["Cards Total", "Buy from", "Rent from", "tix",
                                     "Mythic", "Rare", "Format:", "Event:", "Deck Source:",
                                     "Deck Date:", "Archetype:"]):
            continue
        m = re.match(r"^(\d+)\s+(.+?)(?:\s+\$\s*[\d.]+)?$", line)
        if m:
            qty, name = int(m.group(1)), m.group(2).strip()
            if name and not name.startswith("$"):
                (sideboard if in_sb else maindeck).append({"qty": qty, "name": name})
    return {"maindeck": maindeck, "sideboard": sideboard}


# ─── Banlist Validation ──────────────────────────────────────────────────────

def load_banlist() -> set:
    if not BANLIST_FILE.exists():
        print(f"Warning: Banlist file not found: {BANLIST_FILE}")
        return set()
    with open(BANLIST_FILE) as f:
        data = json.load(f)
    banned = data.get("banned", [])
    return {card["name"] if isinstance(card, dict) else card for card in banned}


def check_legality(cards: list, banlist: set) -> dict:
    banned = [c["name"] for c in cards if c["name"] in banlist]
    return {"legal": len(banned) == 0, "banned_cards": banned}


# ─── Top8 Overlap Detection ──────────────────────────────────────────────────

def load_top8_signatures() -> dict:
    """Build (event_name, player) signatures per archetype from Top8 data."""
    # Find latest top8 decklists file
    decklist_dir = Path("mtg_modern_data/decks/raw/decklists")
    files = sorted(decklist_dir.glob("*_top8_decklists.json"), reverse=True)
    if not files:
        return {}
    with open(files[0]) as f:
        data = json.load(f)
    sigs = {}
    for deck in data.get("decklists", []):
        arch = deck.get("deck_name", "")
        if arch not in sigs:
            sigs[arch] = set()
        sigs[arch].add((deck.get("event_name", "").lower(), deck.get("player", "").lower()))
    return sigs


def is_top8_overlap(archetype: str, player: str, top8_sigs: dict) -> bool:
    canonical = normalize_archetype(archetype)
    for name in [archetype, canonical]:
        if name in top8_sigs:
            for _, p in top8_sigs[name]:
                if p == player.lower():
                    return True
    return False


# ─── Incremental Save ────────────────────────────────────────────────────────

def save_progress(all_decklists, overlap_skipped, output_file, banlist):
    """Save current progress to disk."""
    legal = [d for d in all_decklists if d["legality"]["legal"]]
    illegal = [d for d in all_decklists if not d["legality"]["legal"]]

    output = {
        "format": "Modern",
        "collected_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "MTGGoldfish",
        "period_start": PERIOD_START,
        "total_decks": len(all_decklists),
        "legal_decks": len(legal),
        "illegal_decks": len(illegal),
        "overlap_skipped": overlap_skipped,
        "scraped_at": datetime.now().isoformat(),
        "legality_report": {
            "legal": len(legal),
            "illegal": len(illegal),
            "illegal_decks": [
                {"deck_name": d["deck_name"], "player": d["player"],
                 "banned_cards": d["legality"]["banned_cards"]}
                for d in illegal
            ],
        },
        "decklists": all_decklists,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output


# ─── Cloudflare Retry Helper ─────────────────────────────────────────────────

def navigate_with_retry(page, url, max_retries=3, base_timeout=60000):
    """Navigate to URL with Cloudflare retry logic.
    
    Detects Cloudflare challenge by checking for known challenge indicators:
    - Title contains "Just a moment" or "请稍候"
    - Body contains "security" + "verification"
    - No real page content (short body text)
    
    Waits up to 60s per attempt for user to solve CAPTCHA manually.
    """
    cf_indicators = ["just a moment", "请稍候", "checking your browser",
                     "enable javascript", "cloudflare"]
    
    for attempt in range(max_retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=base_timeout)
            page.wait_for_timeout(3000)

            # Check if Cloudflare challenge is present
            is_cf = False
            try:
                title = page.title().lower()
                body_text = page.query_selector("body").inner_text()[:500].lower()
                
                for indicator in cf_indicators:
                    if indicator in title or indicator in body_text:
                        is_cf = True
                        break
                
                # Also detect: very short body text with no real content
                if len(body_text.strip()) < 200 and not any(
                    kw in body_text for kw in ["tournament", "deck", "modern", "search"]
                ):
                    is_cf = True

            except Exception:
                pass

            if is_cf:
                wait_time = 30 + attempt * 15
                print(f"  Cloudflare challenge detected, waiting up to {wait_time}s (solve CAPTCHA in browser if needed)...")
                
                # Poll for Cloudflare to resolve
                resolved = False
                poll_interval = 3
                elapsed = 0
                while elapsed < wait_time:
                    page.wait_for_timeout(poll_interval * 1000)
                    elapsed += poll_interval
                    try:
                        title = page.title().lower()
                        body_text = page.query_selector("body").inner_text()[:500].lower()
                        still_cf = any(ind in title or ind in body_text for ind in cf_indicators)
                        if not still_cf and len(body_text.strip()) > 200:
                            resolved = True
                            print(f"  Cloudflare resolved after ~{elapsed}s!")
                            break
                    except Exception:
                        pass
                
                if not resolved:
                    if attempt < max_retries - 1:
                        print(f"  Cloudflare not resolved, retrying ({attempt+2}/{max_retries})...")
                        continue
                    else:
                        print(f"  Cloudflare not resolved after {max_retries} attempts")
                        return False

            return True

        except Exception as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 5
                print(f"  Navigation error: {e}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Navigation failed after {max_retries} attempts: {e}")
                return False

    return False


# ─── Browser Profile (persistent context for Cloudflare bypass) ─────────────────

PROFILE_DIR = Path.home() / "Library/Caches/ms-playwright/goldfish-scraper-profile"


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    max_tournaments = 999
    if "--max-tournaments" in sys.argv:
        idx = sys.argv.index("--max-tournaments")
        max_tournaments = int(sys.argv[idx + 1])

    skip_top8_overlap = "--skip-top8-overlap" in sys.argv
    resume = "--resume" in sys.argv

    print(f"=== MTGGoldfish Decklist Scraper ===")
    print(f"Period: {PERIOD_START} ~ today")
    print(f"Max tournaments: {max_tournaments}")
    print(f"Skip Top8 overlap: {skip_top8_overlap}")
    print(f"Resume: {resume}")

    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} banned cards")

    top8_sigs = load_top8_signatures() if skip_top8_overlap else {}
    print(f"Top8 signatures: {len(top8_sigs)} archetypes")

    today = datetime.now().strftime("%m/%d/%Y")
    ps = datetime.strptime(PERIOD_START, "%Y-%m-%d")
    period_start_fmt = ps.strftime("%m/%d/%Y")

    # Output file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"{today_str}_goldfish_decklists.json"

    # Resume: load existing data
    all_decklists = []
    overlap_skipped = 0
    already_scraped_ids = set()

    if resume and output_file.exists():
        try:
            with open(output_file) as f:
                existing = json.load(f)
            all_decklists = existing.get("decklists", [])
            overlap_skipped = existing.get("overlap_skipped", 0)
            already_scraped_ids = {d["event_id"] for d in all_decklists}
            print(f"Resumed: {len(all_decklists)} decks from {len(already_scraped_ids)} tournaments already scraped")
        except Exception as e:
            print(f"Resume failed, starting fresh: {e}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # Use system Chrome (not Playwright's Chromium) — Cloudflare can detect "Chrome for Testing"
        # channel="chrome" launches the real Chrome installed on the system
        # persistent context keeps cookies across runs so Cloudflare only challenges once
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            channel="chrome",  # KEY: use real Chrome, not Chromium
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Minimal anti-detection: just override webdriver flag
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # Step 1: Navigate to tournament search
        print("\nStep 1: Tournament search...")
        search_url = GOLDFISH_TOURNAMENT_SEARCH_URL.format(
            start=period_start_fmt, end=today
        )

        if not navigate_with_retry(page, search_url, max_retries=3, base_timeout=60000):
            print("FATAL: Could not reach Goldfish search page. Aborting.")
            ctx.close()
            # Save whatever we have
            if all_decklists:
                save_progress(all_decklists, overlap_skipped, output_file, banlist)
                print(f"Saved {len(all_decklists)} decks before abort.")
            sys.exit(1)

        print(f"  Title: {page.title()}")

        # Step 2: Get tournament links
        tournaments = page.evaluate("""() => {
            const results = [];
            const anchors = document.querySelectorAll('a[href*="/tournament/"]');
            for (const a of anchors) {
                const href = a.getAttribute('href');
                const match = href.match(/\\/tournament\\/(\\d+)/);
                if (match) {
                    results.push({
                        url: 'https://www.mtggoldfish.com' + href,
                        tournament_id: match[1],
                        name: a.innerText.trim()
                    });
                }
            }
            return results;
        }""")

        # Deduplicate tournaments
        seen_ids = set()
        unique_tournaments = []
        for t in tournaments:
            if t["tournament_id"] not in seen_ids:
                seen_ids.add(t["tournament_id"])
                unique_tournaments.append(t)

        # Filter out League (5-0 only, not full decklists)
        non_league = [t for t in unique_tournaments if "League" not in t["name"]]
        print(f"  Tournaments: {len(unique_tournaments)} total, {len(non_league)} non-league")

        to_scrape = non_league[:max_tournaments]

        # Step 3: Scrape each tournament
        for i, tournament in enumerate(to_scrape):
            tname = tournament['name']
            tid = tournament['tournament_id']

            # Skip already-scraped tournaments in resume mode
            if tid in already_scraped_ids:
                print(f"\n[{i+1}/{len(to_scrape)}] {tname} — SKIPPED (already scraped)")
                continue

            print(f"\n[{i+1}/{len(to_scrape)}] {tname}")

            try:
                if not navigate_with_retry(page, tournament["url"], max_retries=2, base_timeout=30000):
                    print(f"  Could not load tournament page, skipping")
                    continue

                # Get deck entries
                decks = page.evaluate("""() => {
                    const results = [];
                    const rows = document.querySelectorAll('table tbody tr');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 3) {
                            const placement = cells[0]?.innerText?.trim() || '';
                            const archLink = cells[1]?.querySelector('a[href*="/deck/"]');
                            if (!archLink) continue;
                            const href = archLink.getAttribute('href') || '';
                            const deckId = href.split('/deck/')[1]?.split('/')[0] || '';
                            if (deckId) {
                                results.push({
                                    placement,
                                    archetype: archLink.innerText.trim(),
                                    deck_id: deckId,
                                    player: cells[2]?.innerText?.trim() || ''
                                });
                            }
                        }
                    }
                    return results;
                }""")

                # Deduplicate by deck_id
                seen_deck_ids = set()
                unique_decks = []
                for d in decks:
                    if d["deck_id"] not in seen_deck_ids:
                        seen_deck_ids.add(d["deck_id"])
                        unique_decks.append(d)

                print(f"  {len(unique_decks)} unique decks")

                # Filter overlap
                filtered = []
                for d in unique_decks:
                    if skip_top8_overlap and is_top8_overlap(d["archetype"], d["player"], top8_sigs):
                        overlap_skipped += 1
                        continue
                    filtered.append(d)

                if skip_top8_overlap:
                    print(f"  After overlap filter: {len(filtered)} (skipped {len(unique_decks)-len(filtered)})")

                # Expand each deck and parse
                tournament_decks = []
                for j, deck_info in enumerate(filtered):
                    try:
                        # Click Expand for this deck
                        expand_links = page.query_selector_all("a:has-text('Expand')")
                        if j >= len(expand_links):
                            print(f"    [{j+1}] No Expand link, skipping")
                            continue

                        expand_links[j].click()
                        page.wait_for_timeout(1500)

                        # Parse using data-card-name attributes (most reliable)
                        decklist = parse_deck_from_data_attrs(page, deck_info["deck_id"])

                        # Fallback to text parsing
                        if not decklist["maindeck"]:
                            decklist = parse_deck_from_text(page, deck_info["deck_id"])

                        md_count = sum(c["qty"] for c in decklist["maindeck"])
                        sb_count = sum(c["qty"] for c in decklist["sideboard"])

                        # Collapse
                        collapse_links = page.query_selector_all("a:has-text('Collapse')")
                        if collapse_links:
                            collapse_links[0].click()
                            page.wait_for_timeout(500)

                        # Validate legality
                        all_cards = decklist["maindeck"] + decklist["sideboard"]
                        legality = check_legality(all_cards, banlist) if banlist else {"legal": True, "banned_cards": []}

                        result = {
                            "source": "mtggoldfish",
                            "deck_id": deck_info["deck_id"],
                            "deck_name": deck_info["archetype"],
                            "deck_name_canonical": normalize_archetype(deck_info["archetype"]),
                            "player": deck_info["player"],
                            "placement": deck_info["placement"],
                            "event_name": tournament["name"],
                            "event_id": tournament["tournament_id"],
                            "maindeck": decklist["maindeck"],
                            "sideboard": decklist["sideboard"],
                            "maindeck_count": md_count,
                            "sideboard_count": sb_count,
                            "legality": legality,
                        }
                        all_decklists.append(result)
                        tournament_decks.append(result)

                        status = "OK" if legality["legal"] else f"BANNED:{legality['banned_cards']}"
                        print(f"    [{j+1}] {deck_info['placement']} {deck_info['archetype']} "
                              f"by {deck_info['player']}: {md_count}+{sb_count} {status}")

                        time.sleep(0.2)

                    except Exception as e:
                        print(f"    [{j+1}] Error: {e}")
                        try:
                            collapse_links = page.query_selector_all("a:has-text('Collapse')")
                            if collapse_links:
                                collapse_links[0].click()
                                page.wait_for_timeout(500)
                        except:
                            pass
                        continue

                # Incremental save after each tournament
                if tournament_decks:
                    save_progress(all_decklists, overlap_skipped, output_file, banlist)
                    print(f"  Saved progress: {len(all_decklists)} total decks")

                time.sleep(0.5)

            except Exception as e:
                print(f"  Tournament error: {e}")
                # Save progress before continuing
                if all_decklists:
                    save_progress(all_decklists, overlap_skipped, output_file, banlist)
                    print(f"  Saved progress on error: {len(all_decklists)} total decks")
                continue

        ctx.close()

    # Final save
    output = save_progress(all_decklists, overlap_skipped, output_file, banlist)

    print(f"\n{'='*80}")
    print(f"Output: {output_file}")
    print(f"Total: {len(all_decklists)} | Legal: {output['legal_decks']} | Illegal: {output['illegal_decks']}")
    print(f"Top8 overlap skipped: {overlap_skipped}")

    arch_counter = Counter(d["deck_name_canonical"] for d in all_decklists)
    print(f"\nArchetype distribution ({len(arch_counter)} unique):")
    for name, count in arch_counter.most_common():
        print(f"  {count:3d}x {name}")


if __name__ == "__main__":
    main()

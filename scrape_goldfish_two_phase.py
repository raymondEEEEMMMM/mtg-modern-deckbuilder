#!/usr/bin/env python3
"""
MTGGoldfish Two-Phase Decklist Scraper

Phase 1: Scrape tournament list and save as index table
Phase 2: Incrementally scrape decklists from each tournament
  - Marks completed tournaments
  - Skips already-scraped on resume
  - Slow, polite requests to avoid DDoS detection

Usage:
  python3 scrape_goldfish_two_phase.py [--resume] [--max-tournaments N]

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.period_utils import resolve_period_args

# ─── Config ───────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("mtg_modern_data/decks/raw/decklists")
BANLIST_FILE = Path("mtg_modern_data/ban_list/current.json")
INDEX_FILE = OUTPUT_DIR / "goldfish_tournament_index.json"

META_FILE = Path("mtg_modern_data/ban_list/meta.json")
DEFAULT_PERIOD_START = "2026-05-18"  # fallback when meta.json is missing

GOLDFISH_TOURNAMENT_SEARCH_URL = (
    "https://www.mtggoldfish.com/tournament_searches/create?"
    "tournament_search%5Bname%5D=&tournament_search%5Bformat%5D=modern"
    "&tournament_search%5Bdate_range%5D={start}+-+{end}&commit=Search"
)


def build_search_url(period_start: str, period_end: str) -> str:
    """Build Goldfish tournament search URL using MM/DD/YYYY for both bounds."""
    ps = datetime.strptime(period_start, "%Y-%m-%d")
    pe = datetime.strptime(period_end, "%Y-%m-%d")
    return GOLDFISH_TOURNAMENT_SEARCH_URL.format(
        start=ps.strftime("%m/%d/%Y"),
        end=pe.strftime("%m/%d/%Y"),
    )

# Delays between requests (seconds) - be polite!
DELAY_BETWEEN_TOURNAMENTS = 3.0
DELAY_BETWEEN_PAGES = 2.0

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
    "Temur Prowess": "UR Prowess",
    "Izzet Phoenix": "Izzet Phoenix",
}


def normalize_archetype(name: str) -> str:
    return GOLDFISH_TO_CANONICAL.get(name, name)


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


# ─── Cloudflare Retry Helper ─────────────────────────────────────────────────

CF_INDICATORS = ["just a moment", "请稍候", "checking your browser",
                 "enable javascript", "cloudflare"]


def navigate_with_retry(page, url, max_retries=3, base_timeout=60000):
    for attempt in range(max_retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=base_timeout)
            page.wait_for_timeout(3000)

            is_cf = False
            try:
                title = page.title().lower()
                body_el = page.query_selector("body")
                body_text = body_el.inner_text()[:500].lower() if body_el else ""

                for indicator in CF_INDICATORS:
                    if indicator in title or indicator in body_text:
                        is_cf = True
                        break

                if len(body_text.strip()) < 200 and not any(
                    kw in body_text for kw in ["tournament", "deck", "modern", "search"]
                ):
                    is_cf = True
            except Exception:
                pass

            if is_cf:
                wait_time = 30 + attempt * 15
                print(f"  Cloudflare challenge detected, waiting up to {wait_time}s...")
                resolved = False
                elapsed = 0
                while elapsed < wait_time:
                    page.wait_for_timeout(3000)
                    elapsed += 3
                    try:
                        title = page.title().lower()
                        body_el = page.query_selector("body")
                        body_text = body_el.inner_text()[:500].lower() if body_el else ""
                        still_cf = any(ind in title or ind in body_text for ind in CF_INDICATORS)
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


# ─── Index Management ────────────────────────────────────────────────────────

def load_index() -> dict:
    if INDEX_FILE.exists():
        with open(INDEX_FILE) as f:
            return json.load(f)
    return {"tournaments": [], "summary": {"total": 0, "league_skipped": 0, "non_league": 0, "pending": 0, "completed": 0, "failed": 0}}


def save_index(index: dict):
    # Recalculate summary
    total = len(index["tournaments"])
    league = sum(1 for t in index["tournaments"] if t.get("is_league"))
    non_league = total - league
    completed = sum(1 for t in index["tournaments"] if t.get("status") == "completed")
    failed = sum(1 for t in index["tournaments"] if t.get("status") == "failed")
    pending = sum(1 for t in index["tournaments"] if t.get("status") == "pending")
    skipped = sum(1 for t in index["tournaments"] if t.get("status") == "skipped")

    index["summary"] = {
        "total": total,
        "league_skipped": league,
        "non_league": non_league,
        "pending": pending,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
    }
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def load_decklists(output_file: Path) -> list:
    if output_file.exists():
        try:
            with open(output_file) as f:
                data = json.load(f)
            return data.get("decklists", [])
        except Exception:
            return []
    return []


def save_decklists(all_decklists: list, overlap_skipped: int, output_file: Path, banlist: set, period_start: str, period_end: str):
    legal = [d for d in all_decklists if d["legality"]["legal"]]
    illegal = [d for d in all_decklists if not d["legality"]["legal"]]

    output = {
        "format": "Modern",
        "collected_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "MTGGoldfish",
        "period_start": period_start,
        "period_end": period_end,
        "total_decks": len(all_decklists),
        "legal_decks": len(legal),
        "illegal_decks": len(illegal),
        "overlap_skipped": overlap_skipped,
        "scraped_at": datetime.now().isoformat(),
        "legality_report": {
            "legal": len(legal),
            "illegal": len(illegal),
            "illegal_decks": list({
                (d["deck_name"], d["player"], tuple(d["legality"]["banned_cards"])):
                {"deck_name": d["deck_name"], "player": d["player"],
                 "banned_cards": d["legality"]["banned_cards"]}
                for d in illegal
            }.values()),
        },
        "decklists": all_decklists,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    return output


# ─── Browser Profile ─────────────────────────────────────────────────────────

PROFILE_DIR = Path.home() / "Library/Caches/ms-playwright/goldfish-scraper-profile"


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    max_tournaments = 999
    if "--max-tournaments" in sys.argv:
        idx = sys.argv.index("--max-tournaments")
        max_tournaments = int(sys.argv[idx + 1])

    resume = "--resume" in sys.argv
    skip_top8_overlap = "--skip-top8-overlap" in sys.argv
    start_arg = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else None
    end_arg = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else None

    period = resolve_period_args(
        start=start_arg,
        end=end_arg,
        meta_path=META_FILE,
        fallback=DEFAULT_PERIOD_START,
    )
    period_start, period_end = period.start, period.end

    print(f"=== MTGGoldfish Two-Phase Decklist Scraper ===")
    print(f"Period: {period_start} ~ {period_end}")
    print(f"Max tournaments: {max_tournaments}")
    print(f"Skip Top8 overlap: {skip_top8_overlap}")
    print(f"Resume: {resume}")
    print(f"Delay between tournaments: {DELAY_BETWEEN_TOURNAMENTS}s")

    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} banned cards")

    top8_sigs = load_top8_signatures() if skip_top8_overlap else {}
    print(f"Top8 signatures: {len(top8_sigs)} archetypes")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"{today_str}_goldfish_decklists.json"

    # Load existing data
    index = load_index()
    all_decklists = load_decklists(output_file)
    overlap_skipped = 0
    already_scraped_ids = set()

    if output_file.exists():
        try:
            with open(output_file) as f:
                existing = json.load(f)
            overlap_skipped = existing.get("overlap_skipped", 0)
        except Exception:
            pass

    if resume:
        for t in index.get("tournaments", []):
            if t.get("status") == "completed":
                already_scraped_ids.add(t["tournament_id"])
        print(f"Resume: {len(already_scraped_ids)} tournaments already scraped, {len(all_decklists)} decks loaded")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # ── Phase 1: Build/refresh tournament index ──
        pending_tournaments = [
            t for t in index.get("tournaments", [])
            if t.get("status") == "pending" and not t.get("is_league")
        ]

        if not pending_tournaments and not resume:
            print("\nPhase 1: Building tournament index...")
            pe = datetime.strptime(period_end, "%Y-%m-%d")
            period_end_fmt = pe.strftime("%m/%d/%Y")
            ps = datetime.strptime(period_start, "%Y-%m-%d")
            period_start_fmt = ps.strftime("%m/%d/%Y")

            search_url = build_search_url(period_start, period_end)

            if not navigate_with_retry(page, search_url, max_retries=3, base_timeout=60000):
                print("FATAL: Could not reach Goldfish search page. Aborting.")
                ctx.close()
                sys.exit(1)

            print(f"  Title: {page.title()}")

            # Extract all tournaments across paginated pages
            all_tournaments = []
            current_page = 1

            while True:
                tournaments = page.evaluate("""() => {
                    const results = [];
                    const rows = document.querySelectorAll('table tbody tr');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 4) {
                            const nameLink = cells[1]?.querySelector('a');
                            const href = nameLink?.getAttribute('href') || '';
                            const tidMatch = href.match(/\\/tournament\\/(\\d+)/);
                            const nameText = nameLink?.innerText?.trim() || '';
                            results.push({
                                tournament_id: tidMatch ? tidMatch[1] : '',
                                name: nameText,
                                url: href ? 'https://www.mtggoldfish.com' + href : '',
                                date: cells[0]?.innerText?.trim() || '',
                                deck_count: parseInt(cells[3]?.innerText?.trim()) || 0,
                                format: cells[2]?.innerText?.trim() || ''
                            });
                        }
                    }
                    return results;
                }""")

                # Deduplicate
                seen = {t["tournament_id"] for t in all_tournaments}
                for t in tournaments:
                    if t["tournament_id"] and t["tournament_id"] not in seen:
                        all_tournaments.append(t)
                        seen.add(t["tournament_id"])

                print(f"  Page {current_page}: {len(tournaments)} tournaments, total {len(all_tournaments)}")

                # Check for next page
                next_links = page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href*="page="]');
                    const pages = new Set();
                    for (const a of links) {
                        const match = a.href.match(/page=(\\d+)/);
                        if (match) pages.add(parseInt(match[1]));
                    }
                    return [...pages].sort((a,b) => a-b);
                }""")

                next_page = current_page + 1
                if next_page in next_links:
                    # Navigate to next page
                    page.click(f'a[href*="page={next_page}"]')
                    page.wait_for_timeout(2000)
                    current_page = next_page
                    time.sleep(DELAY_BETWEEN_PAGES)
                else:
                    break

            # Build index with status
            index_tournaments = []
            for t in all_tournaments:
                is_league = "League" in t["name"]
                index_tournaments.append({
                    **t,
                    "is_league": is_league,
                    "status": "skipped" if is_league else "pending",
                    "decklists_scraped": 0,
                })

            index["tournaments"] = index_tournaments
            index["format"] = "Modern"
            index["collected_date"] = today_str
            index["source"] = "MTGGoldfish"
            index["search_period"] = f"{period_start_fmt} - {period_end_fmt}"
            save_index(index)
            print(f"  Index saved: {len(index_tournaments)} tournaments")
            print(f"  League (skipped): {sum(1 for t in index_tournaments if t.get('is_league'))}")
            print(f"  Non-league (pending): {sum(1 for t in index_tournaments if not t.get('is_league'))}")
        elif not pending_tournaments and resume:
            print(f"\nNo pending tournaments in index. All done!")
            ctx.close()
            return

        # ── Phase 2: Scrape decklists ──
        pending = [t for t in index.get("tournaments", [])
                   if t.get("status") == "pending" and not t.get("is_league")]

        print(f"\nPhase 2: Scraping decklists from {len(pending)} pending tournaments")

        scraped_count = 0
        for i, tournament in enumerate(pending):
            if scraped_count >= max_tournaments:
                print(f"\nReached max_tournaments limit ({max_tournaments})")
                break

            tname = tournament['name']
            tid = tournament['tournament_id']

            if tid in already_scraped_ids:
                print(f"\n[{i+1}/{len(pending)}] {tname} — SKIPPED (already scraped)")
                continue

            print(f"\n[{i+1}/{len(pending)}] {tname} ({tournament.get('date', '')})")

            try:
                if not navigate_with_retry(page, tournament["url"], max_retries=2, base_timeout=30000):
                    print(f"  Could not load tournament page, marking as failed")
                    tournament["status"] = "failed"
                    save_index(index)
                    continue

                # Click "Expand Decks" to expand all at once
                expand_success = False
                try:
                    expand_all = page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const expandDecks = links.find(a => a.textContent.trim() === 'Expand Decks');
                        if (expandDecks) { expandDecks.click(); return true; }
                        return false;
                    }""")
                    if expand_all:
                        expand_success = True
                        # Scroll down slowly to trigger lazy loading of all decklists
                        page.evaluate("""async () => {
                            let pos = 0;
                            const step = 500;
                            while (pos < document.body.scrollHeight) {
                                pos += step;
                                window.scrollTo(0, pos);
                                await new Promise(r => setTimeout(r, 300));
                            }
                        }""")
                        page.wait_for_timeout(3000)
                        # Scroll back to top
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"  Expand Decks click failed: {e}")

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

                # Parse all expanded decklists
                decklists_data = page.evaluate("""() => {
                    const results = [];
                    const deckContainers = document.querySelectorAll('[id*="deck-"][id*="-tab"]');

                    for (const container of deckContainers) {
                        const idMatch = container.id.match(/deck-(\\d+)-tab/);
                        if (!idMatch) continue;
                        const deckId = idMatch[1];

                        const table = container.querySelector('.deck-view-deck-table');
                        if (!table) continue;

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

                        results.push({
                            deck_id: deckId,
                            maindeck_count: maindeck.reduce((s, c) => s + c.qty, 0),
                            sideboard_count: sideboard.reduce((s, c) => s + c.qty, 0),
                            maindeck: maindeck,
                            sideboard: sideboard
                        });
                    }
                    return results;
                }""")

                # Build decklist map
                decklist_map = {d["deck_id"]: d for d in decklists_data}

                # Check for empty decklists - need individual Expand clicks
                empty_deck_ids = [deck_info["deck_id"] for deck_info in filtered
                                  if decklist_map.get(deck_info["deck_id"], {}).get("maindeck_count", 0) == 0]

                if empty_deck_ids:
                    print(f"  {len(empty_deck_ids)} decks need individual Expand, clicking one by one...")
                    # Click individual Expand links for decks with empty decklists
                    expand_links = page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        return links.filter(a => a.textContent.trim() === 'Expand').length;
                    }""")
                    print(f"  Found {expand_links} individual Expand links")

                    for j in range(min(len(empty_deck_ids), expand_links)):
                        try:
                            # Click the j-th Expand link
                            page.evaluate(f"""(idx) => {{
                                const links = Array.from(document.querySelectorAll('a'));
                                const expandLinks = links.filter(a => a.textContent.trim() === 'Expand');
                                if (expandLinks[idx]) expandLinks[idx].click();
                            }}""", j)
                            page.wait_for_timeout(1500)
                        except Exception as e:
                            print(f"    Expand click {j+1} failed: {e}")

                    # Re-parse decklists after individual expands
                    decklists_data2 = page.evaluate("""() => {
                        const results = [];
                        const deckContainers = document.querySelectorAll('[id*="deck-"][id*="-tab"]');
                        for (const container of deckContainers) {
                            const idMatch = container.id.match(/deck-(\\d+)-tab/);
                            if (!idMatch) continue;
                            const deckId = idMatch[1];
                            const table = container.querySelector('.deck-view-deck-table');
                            if (!table) continue;
                            const maindeck = [];
                            const sideboard = [];
                            let inSideboard = false;
                            const rows = table.querySelectorAll('tr');
                            for (const row of rows) {
                                const header = row.querySelector('th');
                                if (header && header.innerText.trim().startsWith('Sideboard')) {
                                    inSideboard = true; continue;
                                }
                                if (header) continue;
                                const cardName = row.getAttribute('data-card-name');
                                if (cardName) {
                                    const qtyCell = row.querySelector('td');
                                    const qty = qtyCell ? parseInt(qtyCell.innerText.trim()) || 1 : 1;
                                    if (inSideboard) sideboard.push({qty, name: cardName});
                                    else maindeck.push({qty, name: cardName});
                                }
                            }
                            results.push({
                                deck_id: deckId,
                                maindeck_count: maindeck.reduce((s, c) => s + c.qty, 0),
                                sideboard_count: sideboard.reduce((s, c) => s + c.qty, 0),
                                maindeck, sideboard
                            });
                        }
                        return results;
                    }""")
                    # Merge: overwrite empty entries with new data
                    for d in decklists_data2:
                        if d["maindeck_count"] > 0 or d["sideboard_count"] > 0:
                            decklist_map[d["deck_id"]] = d

                # Combine deck entries with parsed decklists
                tournament_decks = []
                for deck_info in filtered:
                    decklist = decklist_map.get(deck_info["deck_id"], {"maindeck": [], "sideboard": []})

                    md_count = decklist.get("maindeck_count", sum(c["qty"] for c in decklist.get("maindeck", [])))
                    sb_count = decklist.get("sideboard_count", sum(c["qty"] for c in decklist.get("sideboard", [])))

                    all_cards = decklist.get("maindeck", []) + decklist.get("sideboard", [])
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
                        "maindeck": decklist.get("maindeck", []),
                        "sideboard": decklist.get("sideboard", []),
                        "maindeck_count": md_count,
                        "sideboard_count": sb_count,
                        "legality": legality,
                    }
                    all_decklists.append(result)
                    tournament_decks.append(result)

                    status = "OK" if legality["legal"] else f"BANNED:{legality['banned_cards']}"
                    print(f"    {deck_info['placement']} {deck_info['archetype']} "
                          f"by {deck_info['player']}: {md_count}+{sb_count} {status}")

                # Mark tournament as completed
                tournament["status"] = "completed"
                tournament["decklists_scraped"] = len(tournament_decks)
                save_index(index)

                # Save decklists incrementally
                if tournament_decks:
                    save_decklists(all_decklists, overlap_skipped, output_file, banlist, period_start=period_start, period_end=period_end)
                    print(f"  Saved progress: {len(all_decklists)} total decks")

                scraped_count += 1

                # Polite delay between tournaments
                if i < len(pending) - 1:
                    print(f"  Waiting {DELAY_BETWEEN_TOURNAMENTS}s before next tournament...")
                    time.sleep(DELAY_BETWEEN_TOURNAMENTS)

            except Exception as e:
                print(f"  Tournament error: {e}")
                tournament["status"] = "failed"
                save_index(index)
                if all_decklists:
                    save_decklists(all_decklists, overlap_skipped, output_file, banlist, period_start=period_start, period_end=period_end)
                    print(f"  Saved progress on error: {len(all_decklists)} total decks")
                continue

        ctx.close()

    # Final save
    output = save_decklists(all_decklists, overlap_skipped, output_file, banlist, period_start=period_start, period_end=period_end)

    print(f"\n{'='*80}")
    print(f"Output: {output_file}")
    print(f"Total: {len(all_decklists)} | Legal: {output['legal_decks']} | Illegal: {output['illegal_decks']}")
    print(f"Top8 overlap skipped: {overlap_skipped}")

    # Print index summary
    index = load_index()
    print(f"\nTournament Index Summary:")
    for key, val in index["summary"].items():
        print(f"  {key}: {val}")

    arch_counter = Counter(d["deck_name_canonical"] for d in all_decklists)
    print(f"\nArchetype distribution ({len(arch_counter)} unique):")
    for name, count in arch_counter.most_common():
        print(f"  {count:3d}x {name}")


if __name__ == "__main__":
    main()

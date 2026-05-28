#!/usr/bin/env python3
"""Quick end-to-end test: scrape 1 tournament from Goldfish, verify decklists saved.

Uses a persistent browser profile so Cloudflare cookies survive between runs.
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrape_decklists_goldfish import (
    OUTPUT_DIR, BANLIST_FILE, PERIOD_START, GOLDFISH_TOURNAMENT_SEARCH_URL,
    normalize_archetype, parse_deck_from_data_attrs, parse_deck_from_text,
    load_banlist, check_legality, load_top8_signatures, is_top8_overlap,
    save_progress, navigate_with_retry,
)

# Persistent profile directory - keeps cookies across runs
PROFILE_DIR = Path.home() / "Library/Caches/ms-playwright/goldfish-scraper-profile"


def test():
    print("=== Goldfish Scraper E2E Test ===")
    print(f"Period: {PERIOD_START}")
    print(f"Profile: {PROFILE_DIR}")

    banlist = load_banlist()
    print(f"Banlist: {len(banlist)} cards")

    top8_sigs = load_top8_signatures()
    print(f"Top8 signatures: {len(top8_sigs)} archetypes")

    today = datetime.now().strftime("%m/%d/%Y")
    ps = datetime.strptime(PERIOD_START, "%Y-%m-%d")
    period_start_fmt = ps.strftime("%m/%d/%Y")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"{today_str}_goldfish_decklists.json"

    if output_file.exists():
        output_file.unlink()
        print(f"Cleaned previous output: {output_file}")

    from playwright.sync_api import sync_playwright

    all_decklists = []
    overlap_skipped = 0

    with sync_playwright() as pw:
        # Use persistent context to keep cookies/session
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        )
        browser = ctx.browser
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Step 1: Navigate to tournament search
        print("\nStep 1: Tournament search...")
        search_url = GOLDFISH_TOURNAMENT_SEARCH_URL.format(
            start=period_start_fmt, end=today
        )

        if not navigate_with_retry(page, search_url, max_retries=3, base_timeout=60000):
            print("FATAL: Could not reach Goldfish search page.")
            print("TIP: If Cloudflare challenge appeared, solve it in the browser window.")
            ctx.close()
            sys.exit(1)

        print(f"  Page title: {page.title()}")

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

        seen_ids = set()
        unique_tournaments = []
        for t in tournaments:
            if t["tournament_id"] not in seen_ids:
                seen_ids.add(t["tournament_id"])
                unique_tournaments.append(t)

        non_league = [t for t in unique_tournaments if "League" not in t["name"]]
        print(f"  Found: {len(unique_tournaments)} total, {len(non_league)} non-league")

        if not non_league:
            print("  No tournaments found! Check Cloudflare or date range.")
            ctx.close()
            sys.exit(1)

        # Step 3: Scrape just 1 tournament
        tournament = non_league[0]
        tname = tournament['name']
        tid = tournament['tournament_id']
        print(f"\nStep 2: Scraping 1 tournament: {tname}")

        if not navigate_with_retry(page, tournament["url"], max_retries=2, base_timeout=30000):
            print("  Could not load tournament page.")
            ctx.close()
            sys.exit(1)

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

        seen_deck_ids = set()
        unique_decks = []
        for d in decks:
            if d["deck_id"] not in seen_deck_ids:
                seen_deck_ids.add(d["deck_id"])
                unique_decks.append(d)

        print(f"  {len(unique_decks)} unique decks found")

        # Filter Top8 overlap
        filtered = []
        for d in unique_decks:
            if is_top8_overlap(d["archetype"], d["player"], top8_sigs):
                overlap_skipped += 1
                continue
            filtered.append(d)
        print(f"  After overlap filter: {len(filtered)} (skipped {len(unique_decks)-len(filtered)})")

        # Only test first 5 decks to keep it fast
        test_decks = filtered[:5]
        print(f"  Testing first {len(test_decks)} decks...")

        for j, deck_info in enumerate(test_decks):
            try:
                expand_links = page.query_selector_all("a:has-text('Expand')")
                if j >= len(expand_links):
                    print(f"    [{j+1}] No Expand link, skipping")
                    continue

                expand_links[j].click()
                page.wait_for_timeout(1500)

                decklist = parse_deck_from_data_attrs(page, deck_info["deck_id"])
                if not decklist["maindeck"]:
                    decklist = parse_deck_from_text(page, deck_info["deck_id"])

                md_count = sum(c["qty"] for c in decklist["maindeck"])
                sb_count = sum(c["qty"] for c in decklist["sideboard"])

                # Collapse
                collapse_links = page.query_selector_all("a:has-text('Collapse')")
                if collapse_links:
                    collapse_links[0].click()
                    page.wait_for_timeout(500)

                all_cards = decklist["maindeck"] + decklist["sideboard"]
                legality = check_legality(all_cards, banlist) if banlist else {"legal": True, "banned_cards": []}

                result = {
                    "source": "mtggoldfish",
                    "deck_id": deck_info["deck_id"],
                    "deck_name": deck_info["archetype"],
                    "deck_name_canonical": normalize_archetype(deck_info["archetype"]),
                    "player": deck_info["player"],
                    "placement": deck_info["placement"],
                    "event_name": tname,
                    "event_id": tid,
                    "maindeck": decklist["maindeck"],
                    "sideboard": decklist["sideboard"],
                    "maindeck_count": md_count,
                    "sideboard_count": sb_count,
                    "legality": legality,
                }
                all_decklists.append(result)

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

        ctx.close()

    # Save output
    output = save_progress(all_decklists, overlap_skipped, output_file, banlist)

    print(f"\n{'='*60}")
    print(f"E2E Test Result:")
    print(f"  Output: {output_file}")
    print(f"  Exists: {output_file.exists()}")
    print(f"  Size: {output_file.stat().st_size} bytes")
    print(f"  Total decks: {len(all_decklists)}")
    print(f"  Legal: {output['legal_decks']}")
    print(f"  Illegal: {output['illegal_decks']}")
    print(f"  Top8 overlap skipped: {overlap_skipped}")

    if all_decklists:
        print(f"\n  Sample decklist:")
        d = all_decklists[0]
        print(f"    {d['deck_name']} ({d['deck_name_canonical']}) by {d['player']}")
        print(f"    Maindeck: {d['maindeck_count']} cards, Sideboard: {d['sideboard_count']} cards")
        if d['maindeck']:
            print(f"    First 5 cards: {d['maindeck'][:5]}")
        print(f"\n  ✅ E2E TEST PASSED: Decklists saved successfully!")
    else:
        print(f"\n  ❌ E2E TEST FAILED: No decklists scraped!")

    return len(all_decklists) > 0


if __name__ == "__main__":
    success = test()
    sys.exit(0 if success else 1)

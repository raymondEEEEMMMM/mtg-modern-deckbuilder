#!/usr/bin/env python3
"""
MTGO official Modern decklist scraper PoC.

The first version is intentionally conservative:
  - render mtgo.com pages with Playwright
  - save raw text/html snapshots
  - parse obvious decklist blocks when present
  - produce a quality report before any main-pipeline integration
"""

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "mtg_modern_data"
META_PATH = DATA_DIR / "ban_list" / "meta.json"
BANLIST_PATH = DATA_DIR / "ban_list" / "current.json"
OUTPUT_DIR = DATA_DIR / "sources" / "mtgo"
RAW_DIR = OUTPUT_DIR / "raw"
URLS_FILE = OUTPUT_DIR / "modern_urls.txt"
DECKLISTS_PATH = OUTPUT_DIR / "mtgo_decklists.json"
REPORT_PATH = OUTPUT_DIR / "mtgo_quality_report.json"
MTGO_DECKLIST_INDEX = "https://www.mtgo.com/decklists"


CARD_LINE_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
DATE_RE = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})|(\d{1,2})[-/](\d{1,2})[-/](20\d{2})")
CATEGORY_RE = re.compile(r"^([A-Za-z_ ]+) \((\d+)\)$")
TOTAL_CARDS_RE = re.compile(r"^\d+\s+Cards$", re.IGNORECASE)
PLAYER_RE = re.compile(r"^(.+?)\s+\(([^)]+)\)$")


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


def load_banlist() -> set[str]:
    if not BANLIST_PATH.exists():
        return set()
    data = load_json(BANLIST_PATH)
    return set(data.get("banned", []))


def slug_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", slug)[:120] or "mtgo-event"


def is_modern_decklist_url(url: str) -> bool:
    slug = slug_from_url(url).lower()
    return slug.startswith("modern-")


def normalize_date(text: str) -> str:
    match = DATE_RE.search(text or "")
    if not match:
        return ""
    if match.group(1):
        y, m, d = match.group(1), match.group(2), match.group(3)
    else:
        m, d, y = match.group(4), match.group(5), match.group(6)
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def normalize_raw_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def discover_urls(page, max_events: int) -> list[str]:
    page.goto(MTGO_DECKLIST_INDEX, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href*="/decklist/"]'))
          .map(a => a.href)
          .filter(Boolean);
    }""")
    seen = []
    for link in links:
        if not is_modern_decklist_url(link):
            continue
        if link not in seen:
            seen.append(link)
        if len(seen) >= max_events:
            break
    return seen


def split_deck_blocks(text: str) -> list[list[str]]:
    """Split MTGO rendered text on deck separators."""
    blocks = []
    current = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "#":
            if current:
                blocks.append(current)
            current = []
            continue
        if current or line:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def parse_player_header(block: list[str]) -> tuple[str, str]:
    for line in block[:8]:
        match = PLAYER_RE.match(line.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return "", ""


def parse_cards_from_block(block: list[str]) -> tuple[list[dict], list[dict]]:
    maindeck = []
    sideboard = []
    section = "main"
    in_cards = False
    sideboard_target = None
    sideboard_seen = 0

    for line in block:
        lower = line.lower()
        if lower in {"standings", "decklists", "bracket", "rounds"}:
            in_cards = False
            continue
        if lower == "decklist stats":
            in_cards = True
            continue
        category = CATEGORY_RE.match(line)
        if category:
            in_cards = True
            category_name = category.group(1).strip().lower()
            if category_name == "sideboard":
                section = "side"
                sideboard_target = int(category.group(2))
                sideboard_seen = 0
            continue
        if TOTAL_CARDS_RE.match(line):
            in_cards = False
            continue
        if lower == "sideboard" or lower.startswith("sideboard "):
            section = "side"
            in_cards = True
            target_match = re.search(r"\((\d+)\)", line)
            if target_match:
                sideboard_target = int(target_match.group(1))
                sideboard_seen = 0
            continue
        if lower in {"maindeck", "main deck", "mainboard"}:
            section = "main"
            in_cards = True
            continue
        if not in_cards:
            continue
        match = CARD_LINE_RE.match(line)
        if not match:
            continue
        qty = int(match.group(1))
        name = match.group(2).strip()
        card = {"qty": qty, "name": name}
        if section == "side":
            sideboard.append(card)
            sideboard_seen += qty
            if sideboard_target is not None and sideboard_seen >= sideboard_target:
                in_cards = False
        else:
            maindeck.append(card)

    return maindeck, sideboard


def parse_event(url: str, text: str, html: str, banlist: set[str], ps: str) -> dict:
    title = ""
    for line in text.splitlines():
        clean = line.strip()
        lower = clean.lower()
        if clean and (
            "modern" in lower
            or "challenge" in lower
            or "preliminary" in lower
            or "showcase" in lower
            or "league" in lower
        ):
            title = clean
            break

    event_date = normalize_date(text)
    event_id = slug_from_url(url)
    decklists = []
    failed_blocks = 0

    for idx, block in enumerate(split_deck_blocks(text), start=1):
        player, placement = parse_player_header(block)
        maindeck, sideboard = parse_cards_from_block(block)
        maindeck_count = sum(c["qty"] for c in maindeck)
        sideboard_count = sum(c["qty"] for c in sideboard)
        if not player and not maindeck and not sideboard:
            continue
        if maindeck_count < 60:
            failed_blocks += 1
            continue
        all_cards = {c["name"] for c in maindeck + sideboard}
        banned = sorted(all_cards & banlist)
        decklists.append({
            "source": "mtgo",
            "event_id": event_id,
            "event_name": title,
            "event_date": event_date,
            "deck_id": f"{event_id}-{idx}",
            "deck_name": "",
            "deck_name_canonical": "",
            "player": player,
            "placement": placement,
            "maindeck": maindeck,
            "sideboard": sideboard,
            "maindeck_count": maindeck_count,
            "sideboard_count": sideboard_count,
            "legality": {"legal": not banned, "banned_cards": banned},
        })

    return {
        "event": {
            "source": "mtgo",
            "url": url,
            "event_id": event_id,
            "event_name": title,
            "event_date": event_date,
            "in_current_period": bool(event_date and event_date >= ps),
        },
        "decklists": decklists,
        "raw": {
            "text_length": len(text),
            "html_length": len(html),
            "failed_blocks": failed_blocks,
        },
    }


def scrape_urls(urls: list[str], headless: bool, delay: float, save_html: bool) -> tuple[list[dict], list[dict]]:
    ps = period_start()
    banlist = load_banlist()
    events = []
    decklists = []

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        for i, url in enumerate(urls, start=1):
            print(f"[{i}/{len(urls)}] {url}")
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            text = normalize_raw_text(page.evaluate("() => document.body?.innerText || ''"))
            html = page.content() if save_html else ""
            slug = slug_from_url(url)
            (RAW_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")
            if save_html:
                (RAW_DIR / f"{slug}.html").write_text(html, encoding="utf-8")

            parsed = parse_event(url, text, html, banlist, ps)
            events.append({**parsed["event"], **parsed["raw"]})
            decklists.extend(parsed["decklists"])
            time.sleep(delay)

        browser.close()

    return events, decklists


def build_report(events: list[dict], decklists: list[dict]) -> dict:
    legal = sum(1 for d in decklists if d.get("legality", {}).get("legal"))
    main_60 = sum(1 for d in decklists if d.get("maindeck_count") == 60)
    side_15 = sum(1 for d in decklists if d.get("sideboard_count") == 15)
    duplicate_keys = Counter(
        (d.get("event_id"), d.get("player"), d.get("deck_id")) for d in decklists
    )
    duplicates = sum(1 for _, count in duplicate_keys.items() if count > 1)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "MTGO official decklists",
        "period_start": period_start(),
        "summary": {
            "event_count": len(events),
            "current_period_events": sum(1 for e in events if e.get("in_current_period")),
            "decklist_count": len(decklists),
            "legal_decklists": legal,
            "maindeck_60_count": main_60,
            "sideboard_15_count": side_15,
            "duplicate_rows": duplicates,
        },
        "events": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape MTGO official Modern decklists")
    parser.add_argument("--urls", type=Path, default=None, help="File containing mtgo.com decklist URLs")
    parser.add_argument("--discover", action="store_true", help="Discover Modern decklist URLs from mtgo.com/decklists")
    parser.add_argument("--max-events", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--no-html", action="store_true", help="Skip large raw HTML debug snapshots")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    if args.urls:
        urls.extend(read_urls(args.urls))

    if args.discover:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=args.headless)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            urls.extend(discover_urls(page, args.max_events))
            browser.close()

    seen = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    urls = seen[:args.max_events]
    if args.discover and urls:
        URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        URLS_FILE.write_text("\n".join(urls) + "\n", encoding="utf-8")

    if not urls:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not URLS_FILE.exists():
            URLS_FILE.write_text(
                "# Add mtgo.com/decklist/... URLs here, one per line.\n",
                encoding="utf-8",
            )
        raise SystemExit(
            f"No MTGO URLs provided. Add URLs to {URLS_FILE} or run with --discover."
        )

    events, decklists = scrape_urls(
        urls,
        headless=args.headless,
        delay=args.delay,
        save_html=not args.no_html,
    )
    output = {
        "format": "Modern",
        "source": "MTGO",
        "period_start": period_start(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "total_decks": len(decklists),
        "decklists": decklists,
    }
    report = build_report(events, decklists)
    save_json(output, DECKLISTS_PATH)
    save_json(report, REPORT_PATH)

    print(f"Wrote {DECKLISTS_PATH}")
    print(f"Wrote {REPORT_PATH}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

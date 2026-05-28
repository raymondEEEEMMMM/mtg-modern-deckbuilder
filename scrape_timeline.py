#!/usr/bin/env python3
"""
Scrape MTG Fandom Banned and Restricted Cards Timeline
Extract Modern format banlist changes from 2011 onwards
"""

import json
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

URL = "https://mtg.fandom.com/wiki/Banned_and_restricted_cards/Timeline"

class TimelineParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_modern_section = False
        self.current_year = None
        self.current_date = None
        self.entries = []
        self.capture_text = False
        self.text_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Check for section anchors like #2011, #2012, etc.
        if tag == 'span' and 'id' in attrs_dict:
            section_id = attrs_dict['id']
            if re.match(r'20\d{2}', section_id):
                self.current_year = section_id
                self.in_modern_section = True

        # Look for table rows in the timeline
        if tag == 'tr' and self.in_modern_section:
            self.capture_text = True
            self.text_buffer = []

        # Look for table data cells
        if tag == 'td' and self.capture_text:
            self.text_buffer = []

    def handle_endtag(self, tag):
        if tag == 'td' and self.capture_text:
            pass  # Process cell data
        elif tag == 'tr' and self.capture_text:
            self.process_row()
            self.capture_text = False

    def handle_data(self, data):
        if self.capture_text and self.current_year:
            self.text_buffer.append(data.strip())

    def process_row(self):
        if len(self.text_buffer) >= 3:
            date_text = self.text_buffer[0]
            card_text = self.text_buffer[1]
            action_text = self.text_buffer[2] if len(self.text_buffer) > 2 else ""

            # Only process if it looks like a Modern entry
            if any(keyword in action_text.lower() for keyword in ['modern', 'banned', 'restricted']):
                entry = {
                    'year': self.current_year,
                    'date_text': date_text,
                    'card': card_text,
                    'action': action_text
                }
                self.entries.append(entry)

def fetch_page():
    """Fetch the timeline page with proper headers"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    req = urllib.request.Request(URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        print(f"URL: {e.url}")
        return None

def parse_html_simple(html_content):
    """Simple regex-based parser for the timeline"""
    entries = []

    # Find all section headers (years)
    year_pattern = r'<span[^>]*id="(20\d{2})"[^>]*>'

    # Find table rows with ban info
    row_pattern = r'<tr>(.*?)</tr>'
    cell_pattern = r'<td[^>]*>(.*?)</td>'

    current_year = None

    for row_match in re.finditer(row_pattern, html_content, re.DOTALL):
        row_content = row_match.group(1)

        # Extract year from section headers
        year_matches = re.findall(year_pattern, row_content)
        if year_matches:
            current_year = year_matches[0]
            continue

        if not current_year:
            continue

        # Extract cells
        cells = re.findall(cell_pattern, row_content, re.DOTALL)
        if len(cells) >= 2:
            # Clean HTML from cell content
            cell0 = re.sub(r'<[^>]+>', '', cells[0]).strip()
            cell1 = re.sub(r'<[^>]+>', '', cells[1]).strip()
            cell2 = re.sub(r'<[^>]+>', '', cells[2]).strip() if len(cells) > 2 else ""

            # Check if it's Modern related
            if 'modern' in cell2.lower() or 'modern' in cell1.lower():
                entry = {
                    'year': current_year,
                    'date': cell0,
                    'card': cell1,
                    'action': cell2
                }
                entries.append(entry)
                print(f"[{current_year}] {cell0} | {cell1} | {cell2[:50]}...")

    return entries

def main():
    print("Fetching MTG Fandom Timeline...")
    print(f"URL: {URL}\n")

    html = fetch_page()
    if not html:
        print("Failed to fetch page")
        return

    print(f"Page length: {len(html)} bytes\n")
    print("=== Parsing timeline ===\n")

    entries = parse_html_simple(html)

    print(f"\n=== Found {len(entries)} Modern-related entries ===")

    # Save to JSON
    output_file = "mtg_modern_data/ban_list/scraped_timeline.json"
    with open(output_file, 'w') as f:
        json.dump({
            'source_url': URL,
            'fetched_at': datetime.now().isoformat(),
            'entries': entries
        }, f, indent=2)

    print(f"\nSaved to: {output_file}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
MTG Modern Banlist Search Tool
Searches the Modern format banlist with historical snapshot support
"""

import json
import sys
import os
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
DATA_DIR = os.path.join(PROJECT_ROOT, "mtg_modern_data", "ban_list")
CURRENT_PATH = os.path.join(DATA_DIR, "current.json")
META_PATH = os.path.join(DATA_DIR, "meta.json")
HISTORY_DIR = os.path.join(DATA_DIR, "history")

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None

def get_baseline_and_changes():
    """Load baseline and all change events, sorted by date"""
    meta = load_json(META_PATH)
    if not meta:
        return None, []

    baseline_file = meta.get('baseline_file', '')
    baseline_path = os.path.join(HISTORY_DIR, baseline_file)
    baseline = load_json(baseline_path)

    changes = []
    for entry in meta.get('changes_history', []):
        if entry.get('is_baseline'):
            continue
        file_path = os.path.join(HISTORY_DIR, entry.get('file', ''))
        change_data = load_json(file_path)
        if change_data:
            changes.append(change_data)

    # Sort changes by effective_date
    changes.sort(key=lambda x: x.get('effective_date', ''))
    return baseline, changes

def compute_banlist_at_date(baseline, changes, target_date):
    """Compute the banlist at a specific date by applying changes"""

    # Start with baseline's added cards
    if baseline and baseline.get('is_baseline'):
        banned = set(baseline.get('changes', {}).get('added', []))
    elif baseline and baseline.get('banned'):
        banned = set(baseline.get('banned', []))
    else:
        banned = set()

    # Apply changes up to target_date
    for change in changes:
        if change.get('effective_date', '') <= target_date:
            added = change.get('changes', {}).get('added', [])
            removed = change.get('changes', {}).get('removed', [])
            banned.update(added)
            banned.difference_update(removed)

    return sorted(list(banned))

def list_history_snapshots():
    """List all available historical snapshots"""
    meta = load_json(META_PATH)
    if not meta or 'changes_history' not in meta:
        return "No history found."

    result = ["## Available Banlist Snapshots", ""]
    for entry in meta['changes_history']:
        date = entry.get('effective_date', 'Unknown')
        desc = entry.get('description', '')
        is_baseline = entry.get('is_baseline', False)
        marker = "[BASELINE]" if is_baseline else ""
        result.append(f"- **{date}**: {desc} {marker}")

    return "\n".join(result)

def show_snapshot(date):
    """Show banlist snapshot for a specific date"""
    if date == "current" or date == "now":
        data = load_json(CURRENT_PATH)
        if data:
            banned = data.get('banned', [])
            label = "Current Modern Banlist"
            desc = data.get('effective_date', '')
        else:
            return "Current banlist not found."
    else:
        baseline, changes = get_baseline_and_changes()
        if baseline is None:
            return "No history data found."

        banned = compute_banlist_at_date(baseline, changes, date)
        label = f"Modern Banlist at {date}"
        desc = ""

    result = [f"## {label}", f"_{desc}_", ""]
    result.append(f"Total: {len(banned)} cards\n")
    for i, card in enumerate(banned, 1):
        result.append(f"{i:2}. {card}")
    return "\n".join(result)

def show_diff(date1, date2):
    """Compare two banlist snapshots"""
    baseline, changes = get_baseline_and_changes()
    if baseline is None:
        return "No history data found."

    banned1 = set(compute_banlist_at_date(baseline, changes, date1))
    banned2 = set(compute_banlist_at_date(baseline, changes, date2))

    only_in_1 = sorted(banned1 - banned2)
    only_in_2 = sorted(banned2 - banned1)

    result = [f"## Diff: {date1} vs {date2}", ""]

    if not only_in_1 and not only_in_2:
        result.append("No differences found.")
    else:
        if only_in_1:
            result.append(f"### Only in {date1} ({len(only_in_1)} cards)")
            for card in only_in_1:
                result.append(f"- ~~{card}~~ (now legal)")
        if only_in_2:
            result.append(f"\n### Only in {date2} ({len(only_in_2)} cards)")
            for card in only_in_2:
                result.append(f"- **{card}** (now banned)")

    return "\n".join(result)

def search_currentbanlist(search_term):
    """Search current banlist by card name"""
    data = load_json(CURRENT_PATH)
    if not data:
        return "Current banlist not found. Please update banlist first."

    banned = data.get('banned', [])
    search_term = search_term.lower()
    matches = [card for card in banned if search_term in card.lower()]

    if matches:
        result = [f"## Search Results for '{search_term}'", f"Found {len(matches)} matches:", ""]
        for card in matches:
            result.append(f"- {card}")
        return "\n".join(result)
    else:
        return f"No banned cards matching '{search_term}' found."

def show_all():
    """Display all current banned cards"""
    data = load_json(CURRENT_PATH)
    if not data:
        return "Current banlist not found. Please update banlist first."

    banned = data.get('banned', [])
    effective_date = data.get('effective_date', 'Unknown')
    total = data.get('total_banned', len(banned))

    result = [f"## Modern Banned Cards ({total})", f"_Effective Date: {effective_date}_", ""]
    for i, card in enumerate(sorted(banned), 1):
        result.append(f"{i:2}. {card}")
    return "\n".join(result)

def main():
    parser = argparse.ArgumentParser(description='MTG Modern Banlist Search Tool')
    parser.add_argument('search_term', nargs='?', help='Card name to search')
    parser.add_argument('--history', action='store_true', help='List all historical snapshots')
    parser.add_argument('--date', metavar='YYYY-MM-DD', help='Show banlist snapshot for date')
    parser.add_argument('--diff', nargs=2, metavar=('DATE1', 'DATE2'), help='Compare two snapshots')

    args = parser.parse_args()

    if args.history:
        print(list_history_snapshots())
    elif args.date:
        print(show_snapshot(args.date))
    elif args.diff:
        print(show_diff(args.diff[0], args.diff[1]))
    elif args.search_term:
        print(search_currentbanlist(args.search_term))
    else:
        print(show_all())

if __name__ == "__main__":
    main()
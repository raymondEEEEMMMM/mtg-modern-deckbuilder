# MTG Modern Banlist Skill

Search and retrieve cards from the MTG Modern format banlist.

## Usage

```
/mtg_banlist <search_term>
```

## Examples

- `/mtg_banlist` - Display all banned cards in Modern format
- `/mtg_banlist Ponder` - Search for a specific card in the banlist
- `/mtg_banlist artifact` - Search for banned cards by type/attribute

## Data Source

Data is sourced from `mtg_modern_data/ban_list/current.json` which contains the current Modern banlist archived from Scryfall API.

## Implementation

This skill reads from the local banlist cache and provides filtering by card name or attributes.
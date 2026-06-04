---
name: agent-init
description: MTG Modern Meta Agent initialization skill. This skill should be used at session start, or whenever the user wants the agent to assume the MTG Modern Meta Agent role and verify the local knowledge base state. Loads agent persona from docs/agent-prompt.md, detects the current banlist period from ban_list/meta.json, runs a deterministic health check on the four key data products (fused_archetypes, top_decks, card_impact, meta/current.json), and recommends next steps if any product is stale. Triggers on: starting a new MTG analysis session, "initialize agent", "进入 MTG 模式", "load context", or whenever the agent needs to confirm its operating state and data freshness before answering questions.
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.

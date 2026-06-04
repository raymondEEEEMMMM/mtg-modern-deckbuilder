---
name: agent-init
description: Use at the start of a session or whenever the user wants to enter MTG Modern Meta Agent mode. Triggers include "initialize MTG agent", "start MTG session", "进入 MTG 模式", "加载 agent 身份". Loads agent persona, reports current banlist period, checks data freshness.
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    os: ["darwin", "linux"]
---

# Agent Init Skill

Run the project's canonical initialization checklist.

1. Read `docs/agent-init.md` and follow its instructions exactly.
2. Report back to the user in the format specified there.

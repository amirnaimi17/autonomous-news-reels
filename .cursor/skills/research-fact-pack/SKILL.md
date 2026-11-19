---
name: research-fact-pack
description: Gather auditable facts for one real selected news event, checking links, timestamps, independent reports, and duplicates before script generation.
---
# Research fact pack

Use with the `news-researcher` subagent. Consult `.cursor/skills/run-news-pilot/references/data-contract.md`.

1. Prefer an existing Phase 2 `event_id` and source articles. If only an ID is given, inspect actual repo read-only accessors to locate sources. Never guess tables or write to SQLite.
2. Confirm publication is inside 72h only when selecting *new* stories. For previously selected stories, report their true date; never falsify recency.
3. Record title, publisher, full source URL, published/retrieved timestamps and specific verified facts with URL evidence.
4. Distinguish factual reporting from claims by actors, opinions, predictions, and corrections.
5. Flag English/German duplicates not reliably matched by Phase 2 narrow alias/number logic; notify parent rather than overriding persistence.
6. If URL fetch is blocked or data is stale, return BLOCKED or explain uncertainty. Do not invent content.
7. Output the fact pack JSON shape to the parent. Readonly subagents return JSON text; the parent can save it to scratch.

Quality bar: every quantitative assertion in a later Reel must be traceable to an attributed source.

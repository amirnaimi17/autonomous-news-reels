---
name: select-distinct-stories
description: Perform an independent editorial check on Phase 2 chosen events for real-world deduplication, recency, relevance, and source support without changing the selection database.
---
# Editorial selection review

Use `news-editor` after research. The existing Python Phase 2 selection, scoring and permanent event history are authoritative.

- Check event ID and publication dates against stored selections; recommend reuse of the already-selected event for prototype, not a new DB insertion.
- Audit same-event coverage across outlets. Treat shared wire copy as one source, not independent confirmation.
- A household keyword can raise a candidate. It cannot approve one. Borderline stories need the audience assessment in `direct-news-reel`. Reject a globally important story with no supported consequence for life in Germany.
- Distinguish what happened from why commentators think it happened.
- State if a story cannot be responsibly summarized due to unresolved facts.
- Do NOT call `discover`, update `event_selections`, fake rankings, or claim the editor's recommendation has changed the application.

Return `APPROVE | REVISE | REJECT`, rationale, duplicate risk and audience angle. For multiple candidates, return a ranked suggestion and existing event IDs (no new selection records).

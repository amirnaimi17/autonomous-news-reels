---
name: write-reel-script
description: Produce a testable fact-checked four-scene Reel script from an approved source fact pack, with timings and source-linked claims.
---
# Four-scene reel script

Use after `news-editor` approves. Follow `.cursor/skills/run-news-pilot/references/data-contract.md`.

1. Ask/confirm language and intended audience once. For Persian, draft natural spoken Persian and review RTL punctuation, diacritics, numbers and names.
2. Four scenes exactly: (1) truthful hook; (2) verified what happened; (3) verified significance; (4) useful takeaway and attribution. Avoid a misleading call-to-action.
3. Persian Instagram Reels target 40 seconds, acceptable 38–42, so Farid can speak them at a natural rate. Other languages stay 30–50 seconds unless the user sets a length. Each scene has spoken narration, a short mobile caption, an image prompt, and a duration. Captions are **not** full transcriptions.
4. Every material claim, number, date and quotation must appear in `claims` with actual source URLs from fact pack; do not invent an explanation, trend, or outcome.
5. Avoid quoting long copyrighted text and do not misrepresent creative visuals as event footage.
6. Save `story_package.json` to `storage/generated/pilot/<run-id>/`. Do not modify app code or database.
7. Run `python3 .cursor/skills/verify-reel-pilot/scripts/validate_story_package.py <path>` and fix any structural failure. A structural PASS does not replace factual review.

Stop for review after presenting the readable four-scene script. Do not assume consent to generate speech or video.

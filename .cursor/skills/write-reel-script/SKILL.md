---
name: write-reel-script
description: Produce a testable fact-checked four-scene Reel script from an approved source fact pack, with timings and source-linked claims.
---
# Four-scene reel script

Use after `news-editor` approves. Follow `.cursor/skills/run-news-pilot/references/data-contract.md`.

1. Ask/confirm language and intended audience once. For Persian, draft natural spoken Persian and review RTL punctuation, diacritics, numbers and names.
2. Let the brief set the scene count. A complete report has a truthful hook, the context, the key development, why it matters, and a conclusion. Do not force three or four scenes, and do not stop the story early to match an old recording. Name who in Germany is affected. Keep an announcement date separate from the date a rule takes effect. A provider exception stays with that provider.
3. Persian reports aim at 35–45 seconds. Completeness comes first, so a sourced ending may make the script longer. Write natural spoken Persian in short complete sentences, with the attribution in the same sentence as the claim. Do not plan on a faster rate. Digits may stay in the narration field; `persian-tts` prepares the spoken form for Aran. Each scene has spoken narration, a short mobile caption, a visual job, and a duration. Captions are **not** full transcriptions. Set `duration_policy` to `completeness` when the approved script is kept even if it falls outside 35–45 seconds.
4. Every material claim, number, date and quotation must appear in `claims` with actual source URLs from fact pack; do not invent an explanation, trend, or outcome.
5. Avoid quoting long copyrighted text and do not misrepresent creative visuals as event footage.
6. Save `story_package.json` to `storage/generated/pilot/<run-id>/`. Do not modify app code or database.
7. Run `python3 .cursor/skills/verify-reel-pilot/scripts/validate_story_package.py <path>` and fix any structural failure. A structural PASS does not replace factual review.

Stop for review after presenting the readable four-scene script. Do not assume consent to generate speech or video.

---
name: run-news-pilot
description: Manually orchestrate a gated, multi-agent Cursor rehearsal of one news-to-Reel event, without changing the autonomous-news-reels runtime.
disable-model-invocation: true
---
# Run one news-to-Reel pilot

This skill coordinates Cursor subagents. It does NOT turn them into a scheduled service. Always read `references/data-contract.md` first. Work on ONE real selected Phase 2 event; the current focus is proving each stage.

## Safety and scope
- Never change application code, migrations, selected rows or production states during the pilot.
- Do not call `main.py discover` by default. Discovery persists selections. If the user specifically wants a new discovery run, explain that side effect before running it.
- Store only scratch pilot artifacts under `storage/generated/pilot/<run-id>/` (ignored by the current repo `.gitignore`). Never run a production scheduler or publish to Instagram.
- Do not invent article text, sources, completed tests, images, speech files or MP4s. If a tool is missing, stop that stage and explain.
- Ask once for missing essentials: selected event ID (or trusted link), output language (e.g. `fa-IR`), target audience and desired length. Do not keep asking for optional choices.

## Stage gates — STOP after each stage unless user explicitly asks for full pilot
1. **Fact pack.** Delegate to `news-researcher`. Apply `research-fact-pack`. Record referenced event and sources; if BLOCKED, stop.
2. **Editorial.** Delegate to `news-editor`. Apply `select-distinct-stories`, then `direct-news-reel`. Keep the DB selection unchanged. An editorial reject stops the pilot. The brief names the affected audience, the practical consequence, the supporting source, five hooks, the chosen angle, and the visual job of each beat. A keyword hit alone does not approve a borderline story.
3. **Draft script.** Delegate to `reel-scriptwriter`. Apply `write-reel-script`. The brief sets the length. Persian reports aim at 35–45 seconds, and a complete sourced ending may run longer. Do not reuse an old narration. Store `story_package.json`, check the contract, and show the script.
4. **Script review.** `news-editor` checks the script before any paid call. A missing conclusion, an unsupported number, or a cut made only to fit an old file is `REVISE`.
5. **Storyboard.** Delegate to `reel-producer`. Apply `build-reel-storyboard`. Show the visual plan and the cost estimate. Stop and ask before a paid voice or image call.
6. **Draft render.** After that approval, `reel-producer` estimates cost with `reel-cost-tracking` and stops if the estimate is incomplete or above the active cap. Speech is ElevenLabs Aran unless the key is unset, in which case Edge Farid at `+0%` speaks the same approved script. Subtitle times come from the audio just generated. `reel-video-design` builds the 1080×1920 MP4 with Remotion for Persian type and graphics. Do not use espeak-ng, do not raise the speaking rate, and do not call a paid provider without a cleared estimate. Write a new `storage/generated/pilot/<run-id>/` rather than overwriting an older Reel.
7. **Independent QA.** Delegate to `qa-verifier`; apply `verify-reel-pilot` and `reel-quality-assurance`, and check that a cost decision exists. A technical pass is not human approval of the voice or the design. Explicitly separate script PASS from video NOT_RUN.
8. **Promote to app (later).** If *and only if* the user asks, delegate to `integration-architect`; apply `promote-to-runtime`. Approval to propose != approval to code.

## Parent handoff
Subagents with `readonly: true` return findings; the parent Cursor agent may save them as `fact_pack.json` and `editorial_review.json` in the scratch directory. Do not claim subagent changes are automatically shared; pass concise structured findings with paths to the next subagent.

After each stage return: what is real, what is hypothetical, actual file paths, test evidence, blockers, and the **single next proposed step**. Never auto-advance without the requested scope.

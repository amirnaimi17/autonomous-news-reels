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
2. **Editorial.** Delegate to `news-editor`. Apply `select-distinct-stories`. Keep the DB selection unchanged; editorial reject stops the pilot.
3. **Draft script.** Delegate to `reel-scriptwriter`. Apply `write-reel-script`. Persian Reels target 40 seconds (38–42). Store `story_package.json` in scratch; check against contract and show user script.
4. **Storyboard.** Delegate to `reel-producer`. Apply `build-reel-storyboard`, returning `visual_plan.json`; show prompts and timing.
5. **Draft render.** When the user asks for a Reel, `reel-producer` applies `persian-tts` for fa-IR speech and `reel-video-design` for the 1080×1920 MP4 (`render-reel-pilot` is that gate). Do not use espeak-ng. Write a new `storage/generated/pilot/<run-id>/` rather than overwriting an older Reel.
6. **Independent QA.** Delegate to `qa-verifier`; apply `verify-reel-pilot`; explicitly separate script PASS from video NOT_RUN.
7. **Promote to app (later).** If *and only if* the user asks, delegate to `integration-architect`; apply `promote-to-runtime`. Approval to propose != approval to code.

## Parent handoff
Subagents with `readonly: true` return findings; the parent Cursor agent may save them as `fact_pack.json` and `editorial_review.json` in the scratch directory. Do not claim subagent changes are automatically shared; pass concise structured findings with paths to the next subagent.

After each stage return: what is real, what is hypothetical, actual file paths, test evidence, blockers, and the **single next proposed step**. Never auto-advance without the requested scope.

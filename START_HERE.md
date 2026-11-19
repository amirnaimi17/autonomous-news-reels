# Cursor News-to-Reels Agent Kit (pilot only)

This kit was designed for the public `autonomous-news-reels` project whose README reports **Phase 1 and Phase 2 complete**. It does not replace or modify the Python app. It adds Cursor-only markdown subagents and skills for testing one event at a time. It has not been run inside your own Cursor installation yet.

## What is included?

- Six role-based Cursor subagents: `news-researcher`, `news-editor`, `reel-scriptwriter`, `reel-producer`, `qa-verifier`, `integration-architect`.
- Ten skills: `run-news-pilot`, `research-fact-pack`, `select-distinct-stories`, `write-reel-script`, `build-reel-storyboard`, `persian-tts`, `reel-video-design`, `render-reel-pilot`, `verify-reel-pilot`, `promote-to-runtime`. Persian speech and the MP4 stay on `reel-producer`.
- A reusable data contract and a dependency-free JSON structural validator.
- One explicitly **synthetic** story fixture. This fixture must never be published as real news.

Cursor sees these by reading `.cursor/agents/*.md` and `.cursor/skills/*/SKILL.md`. `/run-news-pilot` is the orchestrating skill; the parent Cursor Agent delegates to specialist subagents.

## Install in your local existing repository (recommended)

1. Download `cursor-news-reels-kit.zip` from this chat to `~/Downloads/`.
2. Open a Linux terminal **inside the root folder of your already-cloned autonomous-news-reels repository** (same folder as `main.py`). Do NOT create another nested repository.
3. Run:

```bash
cd /path/to/autonomous-news-reels
unzip -n ~/Downloads/cursor-news-reels-kit.zip -d .
find .cursor/agents .cursor/skills -type f | sort
```

`unzip -n` preserves existing files. If you saved the ZIP elsewhere, replace `~/Downloads/` with the real path. The archive also adds this `START_HERE.md` and an `examples/` fixture (not application code).

4. Open this repository folder in **Cursor desktop**, not a single `.md` file. Refresh/reopen the Cursor window if needed. Open **Customize -> Skills** to view skills, and check `.cursor/agents/` to view subagents.

Project files inside `.cursor/` exist locally but are **not pushed to GitHub unless you explicitly `git add`, commit and push**. Check `git status` to see changes.

## First test: confirm discovery, no API calls or DB edits

Open Cursor chat in **Agent** mode and type:

```text
/news-researcher Inspect this repository read-only. Identify the existing Phase 2 news discovery/selection interfaces, explain how to read the three selected event IDs and their source URLs without changing SQLite, and show how to verify that a selected story is real. Do not run discover, write files, or modify the app. Report any missing information.
```

This is the first gate. The agent should inspect code and return paths/read methods, NOT magically generate a Reel.

**Important:** `python main.py discover` is not a read-only command: it may insert today's selections. Avoid running it casually while testing. For an existing event, reuse its original ID. Your prior successful run reported three selected UUIDs; choose one for this pilot.

## Next manual test (after the first passes)

Ask the parent Cursor Agent:

```text
/run-news-pilot Use the selected Phase 2 event ID <PASTE_REAL_EVENT_ID>. Output language: Persian (fa-IR), audience: people living in Germany, length: about 40 seconds. Do ONLY stage 1 (research/fact pack), delegate to news-researcher, and stop for my review. Do not modify app code or selection history.
```

Then use `/run-news-pilot ... proceed to editorial review only`, and later script, storyboard, render, QA — one gate at a time. The parent can save draft JSON under `storage/generated/pilot/<run-id>/`, which is already excluded by the repo `.gitignore`. You may manually invoke `/news-editor`, `/reel-scriptwriter`, `/reel-producer` or `/qa-verifier` to isolate bugs.

## Offline test of the included validator

```bash
python3 .cursor/skills/verify-reel-pilot/scripts/validate_story_package.py examples/synthetic-story-package.json --allow-demo
```

This should output `PASS: structural checks only ...`. It does NOT prove facts or video quality. Omitting `--allow-demo` should FAIL safely because the fixture is not real news.

## When your pilot step is reliable

Use `/promote-to-runtime` to propose mapping **one** proven step to the real Python provider and orchestrator. Do not allow integration until you approve the file-by-file plan and tests. Prefer small changes to the existing Phase 1–2 contracts, not a rewrite.

When you wish to commit **only the Cursor configuration**:

```bash
git status --short
git add .cursor/agents .cursor/skills START_HERE.md examples/synthetic-story-package.json
git diff --cached --stat
# Review the staged diff carefully before committing and pushing.
```

Do not add `storage/generated/pilot/`, `.env`, SQLite files, or source article data containing sensitive information. We intentionally do **not** create `AGENTS.md`, `.cursor/rules/` or modify your current Python runtime.

## What the kit does NOT do

- It does not run your agents when Cursor is closed, schedule daily news, send Telegram messages or post on Instagram.
- It does not include image generation models, a TTS provider, or automatic video rendering code; the production skills define reproducible gates and prerequisites for later implementation.
- It does not make English/German event dedup reliable beyond the Phase 2 limits.
- It does not create or change the SQLite selection database.

For independent 24/7 execution on a VPS, the tested workflows still need to be implemented in your application's runtime with provider adapters, deterministic tests and a scheduler.

## Troubleshooting

- **No skills displayed:** Check that `SKILL.md` is under `.cursor/skills/<name>/` and that the repository root is open in Cursor. Reload the window.
- **No subagents:** Check `.cursor/agents/<name>.md` and the `name`/`description` YAML frontmatter. Type `/news-researcher ...` in an Agent chat.
- **Slash command not suggested:** Type the full prompt `Use the news-researcher subagent to ...`; verify your Cursor version supports project subagents.
- **Agent claims a Reel exists:** Ask QA for its exact path and ffprobe output. A JSON draft or image prompt is not an MP4.
- **DB changes unexpectedly:** Stop and inspect `git diff`, the configured SQLite path and selection state. Readonly subagents must never run `discover` as a default action.

Docs used for the format: https://cursor.com/docs/subagents and https://cursor.com/docs/skills (checked November 2026).

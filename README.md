# Autonomous News Reels

A standalone Python application that will discover recent news, choose distinct stories, and produce a small number of vertical Instagram Reels each day. Phase 1 is the foundation: configuration, the database, duplicate-identity rules, the daily quota, and offline provider boundaries.

The pipeline does not yet collect RSS, render a reel, or send Telegram messages. Those steps are later phases. Nothing here pretends that they already run.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Structure, configuration, database, quota, provider ports | Implemented |
| 2 | News research, selection, 72-hour rule, duplicate clustering | Not started |
| 3 | Script-writing agent | Not started. An extractive fallback that only copies source sentences is available. |
| 4 | Image and voice agents | Not started. Solid-color frames and silent WAV files exist as offline stand-ins. |
| 5 | FFmpeg reel render and file validation | Not started. Encoder selection and the acceptance rules exist. |
| 6 | Telegram, scheduler, restart recovery of a live run | Not started. The database locks and slot heartbeat exist. |
| 7 | End-to-end runs and deployment verification | Not started |

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/python main.py init-db
.venv/bin/python main.py status
```

Copy `.env.example` to `.env` before adding tokens. The process reads environment variables and that file. Tokens are never printed by `status`.

`INSTAGRAM_PUBLISH_ENABLED` must stay `false`. Setting it to `true` stops the process, because no publisher is installed.

`python main.py scheduler` does not exist yet. The systemd unit in `deploy/news-reels.service` is a template for Phase 6.

## What Phase 1 already enforces

- One client, stored on every row, so a later account does not need a new schema.
- Stories are kept forever. Restarts do not wipe the duplicate history.
- A canonical URL is one article. Tracking parameters, `www`, fragments, and a trailing slash do not create a second row.
- An event fingerprint is unique per client. Two clients may store the same fingerprint.
- A generation job is unique per event. A finished reel cannot be created again.
- A failed job resumes on the same row and the same slot. Retry does not insert a second reel.
- At most `min(daily limit, number of slots)` completed reels per local calendar day. The default is 3, at 09:00, 14:00, and 19:00 in Europe/Berlin.
- A skipped slot or a failed slot does not count toward that limit.
- The repository can close an empty slot with the detail `insufficient_qualifying_news`. That slot stays closed and does not count as a reel. Choosing the shortage is part of the later selection agent.
- Two runs cannot hold the same slot, the same event, or the workflow lock.
- A slot whose heartbeat is older than `SLOT_STALE_SECONDS` (default 45 minutes) is failed and can be reopened. The story binding is kept.
- Generation moves one state at a time: `SELECTED` → `SCRIPT_GENERATED` → `IMAGES_GENERATED` → `AUDIO_GENERATED` → `VIDEO_RENDERED` → `COMPLETED`. `FAILED` resumes from the last state that stored an artifact. `COMPLETED` and `SKIPPED` do not move.
- Narration from the extractive fallback is rejected if it contains a number that is not in the source text.

The 72-hour window, importance scoring, and cross-headline event clustering are specified in `docs/architecture.md` and are implemented in Phase 2. The fingerprint functions those rules will call are already tested.

## Layout

```text
app/agents/            Agent contracts. They do not call each other.
app/orchestrator/      Fixed step order. No runner yet.
app/database/          SQLite schema, state machine, repository.
app/services/          News, image, speech, notification, and dedup ports.
app/core/              Settings, clock, logging, paths.
main.py                Standalone entry point.
```

The orchestrator is the only future writer of a production run. Agents receive request models and return result models.

## Deployment notes

Docker builds a Python 3.12 image with ffmpeg from Debian. That image is for CPU encoding. NVENC stays on the host, where ffmpeg 8.0.1 and the Quadro T2000 have already been confirmed. The container initializes the database and then runs `status` until the scheduler exists.

```bash
docker build -t news-reels .
docker run --rm -v news-reels-data:/data -v news-reels-media:/media news-reels
```

If a bind-mounted volume is owned by root, the container user `appuser` (uid 10001) cannot write to it.

## Tests

`pytest` covers the quota, the canonical URL constraint, concurrent reservation, state transitions, provider fallbacks, and encoder selection. It does not download news or call Telegram.

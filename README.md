# Autonomous News Reels

A standalone Python application that discovers recent news, chooses distinct stories, and will later produce a small number of vertical Instagram Reels each day. Phase 2 collects configured RSS feeds and records a daily selection. It does not render a reel or send Telegram messages.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Structure, configuration, database, quota, provider ports | Implemented |
| 2 | News research, selection, 72-hour rule, duplicate clustering | Implemented. Selection does not start production. |
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
.venv/bin/python main.py discover
```

`discover` reads `NEWS_SOURCES` or `NEWS_SOURCES_FILE`. Both are empty by default, and the command then exits with a configuration error. Copy `config/news_sources.example.json`, replace the example URLs with real feeds, and point the process at that file:

```bash
NEWS_SOURCES_FILE=config/news_sources.json .venv/bin/python main.py discover
```

Each source object needs `name`, `url`, and `language` (`en`, `de`, or another 2–3 letter code). `STOPWORDS_DIR` defaults to `config/stopwords` and is resolved from the current directory. `ENTITY_ALIASES_FILE` is optional. `TRANSLATION_PROVIDER` accepts only `none`.

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

The 72-hour window, importance scoring, and event clustering are implemented by `discover`. The rules and their limits are in `docs/deduplication.md`. Discovery writes articles, events, and `event_selections`. It leaves every event in `DISCOVERED` and does not reserve a slot or create a reel.

## What discovery does

- Keeps articles published from 72 hours ago through 15 minutes ahead. Undated articles are dropped.
- Orders eligible stories as today, then yesterday, then older stories inside the window. An older story must score at least `OLDER_WINDOW_MIN_IMPORTANCE` (default 0.75). Today and yesterday use `MIN_IMPORTANCE_SCORE` (default 0.55).
- Selects up to `DAILY_REEL_LIMIT` events for the local day. The default is 3. The setting accepts 0 through 24. `0` selects nothing. Production slots do not change this number.
- Inserts only missing ranks. A stored rank is never replaced. An event selected on any date is never selected again.
- One failed feed does not drop the other configured feeds.
- Without a translator, English and German text can share an event only through the entity-and-number hint. That is not reliable multilingual deduplication. Paraphrases stay separate.

## Layout

```text
app/agents/            Agent contracts. They do not call each other.
app/orchestrator/      Fixed step order. No runner yet.
app/database/          SQLite schema, state machine, repository.
app/services/          News, image, speech, notification, and dedup ports.
app/core/              Settings, clock, logging, paths.
main.py                Standalone entry point.
```

The orchestrator remains the only future writer of a production run. `discover` writes articles, events, and selection rows through the repository. It does not write `generated_content` or `daily_production`.

## Deployment notes

Docker builds a Python 3.12 image with ffmpeg from Debian. That image is for CPU encoding. NVENC stays on the host, where ffmpeg 8.0.1 and the Quadro T2000 have already been confirmed. The container initializes the database and then runs `status` until the scheduler exists.

```bash
docker build -t news-reels .
docker run --rm -v news-reels-data:/data -v news-reels-media:/media news-reels
```

If a bind-mounted volume is owned by root, the container user `appuser` (uid 10001) cannot write to it.

## Tests

`pytest` covers the quota, canonical URLs, concurrent slot reservation, state transitions, provider boundaries, encoder selection, clustering, scoring, incremental selection, and selection races across two connections and two processes. It does not download live news or call Telegram. The project config is quiet; this prints the pass count:

```bash
.venv/bin/pytest -o addopts=
```

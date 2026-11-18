# Architecture

Phase 1 builds the skeleton the later agents plug into. The production run is one orchestrator calling specialized agents. Agents do not start the workflow and they do not talk to each other.

## Components

| Piece | Responsibility | Writes the database |
| --- | --- | --- |
| Scheduler (Phase 6) | Fires a slot, catches up a missed slot after a restart, refreshes the lock | No. It asks the orchestrator. |
| Orchestrator | Orders the steps and commits each artifact | Yes. It is the only writer. |
| News research agent | Reads configured sources and returns articles | No |
| News selection agent | Applies the window, the score, and duplicate history | No. It receives history as input. |
| Script, image, voice, video, notification agents | One transformation each | No |
| Repository | Transactions, uniqueness, quota, state machine | Yes |

Research and selection are proposals. `reserve_slot` and `reserve_story` are the commit points. If story reservation loses a race, the orchestrator asks selection for the next candidate before any media work starts. Once a slot is bound to an event, that slot does not switch stories.

The step order is fixed:

1. Research
2. Select
3. Reserve the production slot, which also checks the daily quota
4. Reserve the story
5. Write the script
6. Generate images
7. Generate voice
8. Render video
9. Validate the file
10. Mark the reel completed
11. Notify

Each artifact step commits before the next one starts. A crash resumes from `last_successful_state` on the same `generated_content` row. That is what “retry without a duplicate” means.

`DISCOVERED` is the event state used before a slot claims it. The content row starts at `SELECTED`. The remaining states live on `generated_content` and are copied onto the event in the same transaction.

## Duplicate prevention

Five checks, applied in this order. An uncertain result is a duplicate when `FAIL_CLOSED_DEDUPLICATION` is true, which is the default. Missing a reel is acceptable. Repeating one is not.

1. **Canonical URL.** Scheme and host are lowercased, `www` is removed, the fragment is dropped, tracking parameters (`utm_*`, `fbclid`, `gclid`, and a short list of campaign ids) are dropped, the remaining query is sorted, and a trailing slash is removed. The database unique key is `(client_id, canonical_url)`. This check is already enforced on write.
2. **Normalized headline.** Lowercase, punctuation folded, and a trailing outlet name such as “BBC News” removed. The fingerprint is a hash of the sorted significant tokens, so word order alone does not create a new story. A place name after a hyphen is kept, so “Election results - France” and “Election results - Germany” stay distinct.
3. **Entity and event match.** Phase 2 clusters articles that share entities and an event description. The event row stores entities, a block key, source URLs, and a fingerprint unique per client.
4. **Semantic similarity.** SimHash of the summary, compared by Hamming distance. Default threshold is 8 bits of 64. Embeddings have a column reserved for a later provider. They are not required.
5. **Related-event rule.** A new article about an event that already has a reel is stored as an update. In this version it does not become another reel, even when the development is important.

The optional semantic judge returns `same_event`, `update`, `distinct`, or `uncertain`. The shipped judge always returns `uncertain`. With fail-closed deduplication, that does not open a new reel.

Headline clustering itself is Phase 2. Phase 1 stores the fields, enforces URL and event uniqueness, and tests the fingerprint functions the clusterer will call.

## Daily quota

The client timezone decides the production date. A slot at 19:00 in Berlin belongs to that Berlin date even if UTC has rolled over.

Defaults:

- Timezone: `Europe/Berlin`
- Slots: 09:00, 14:00, 19:00
- Completed reels per local day: 3, and never more than the number of slots

`reserve_daily_slot` runs inside `BEGIN IMMEDIATE`:

- Count slots with status `COMPLETED` for that client and local date.
- If the count is at the limit, raise a quota error. Do not borrow an older story.
- If another slot for that client is `RUNNING` and its heartbeat is fresh, refuse. One run at a time.
- If a running slot’s heartbeat is older than 45 minutes, mark it `FAILED` and, when it is the slot being started, reopen it on the same event.
- `SKIPPED` and `FAILED` do not count as reels. A skipped slot stays closed. The next slot may still produce a reel.
- An empty slot can be stored with detail `insufficient_qualifying_news`. The selection agent decides that in Phase 2. `record_notification` stores the owner message; Phase 6 delivers it.

The workflow lock is a second guard for two processes. Slot reservation still behaves correctly if the lock is bypassed.

## Providers and cost

No provider credential is required to boot, test, or initialize the database.

| Capability | Phase 1 behavior | Later option | Typical cost |
| --- | --- | --- | --- |
| News | Interface only. RSS client is Phase 2. Default feeds are BBC, NYT, Guardian, Al Jazeera, and NPR. | Keep RSS. A paid API is optional. | $0 for public RSS |
| Script | Extractive fallback copies source sentences and refuses new numbers. | A small model behind the same request model. | About $0.001 per reel on a mini model, or $0 offline |
| Images | Solid PPM frame. News cards must not invent a photograph of an event. | Typographic cards via Pillow, or a sourced photo. Generative images stay optional because they can fabricate scenes. | $0 for cards. Generative images are often $0.02–$0.08 each. |
| Voice | Silent WAV sized from the word count. This is not a voice. | Configurable TTS. Roughly $0.01 per reel for a cloud voice. | $0 until a voice is chosen |
| Video | Encoder probe. `auto` picks `h264_nvenc` on this machine, else `libx264`. | FFmpeg render at 1080×1920. | $0, local encode |
| Notification | In-memory log notifier. | Telegram Bot API. | $0 |
| Instagram | Flag exists and defaults off. `true` refuses to start. | Explicit publisher, still off by default. | Platform account only |

Three reels a day with RSS, typographic cards, and one paid voice is on the order of a few dollars a month. The Quadro T2000 has 4 GB of VRAM. The design does not load a large local model for the core path. NVENC is used only as an encoder.

## Multi-client seam

The MVP runs one client, `default`. These choices leave room for more accounts without a rewrite:

- `client_id` is on every table and inside the uniqueness keys.
- Settings already name the timezone, slots, limit, providers, and language fields the script model carries.
- Media paths are created in one function.
- Provider choice is a factory, not a hardcoded SDK.
- Usage rows can be added later beside `agent_execution_logs` and `notifications`.

There is no tenant administration UI and no shared scheduler for many accounts.

## Database

SQLite in WAL mode, with foreign keys and a migration table. `NewsReelsRepository` is the boundary a PostgreSQL implementation can replace. The schema file is `app/database/migrations/001_initial.sql`.

Tables: `clients`, `news_articles`, `news_events`, `generated_content`, `daily_production`, `agent_execution_logs`, `notifications`, `app_config`, `job_locks`, `schema_migrations`.

Normal operation does not delete articles, events, or finished reels. The duplicate history has to outlive the process.

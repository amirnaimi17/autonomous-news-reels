# Architecture

Phase 1 builds the skeleton the later agents plug into. The production run is one orchestrator calling specialized agents. Agents do not start the workflow and they do not talk to each other.

## Components

| Piece | Responsibility | Writes the database |
| --- | --- | --- |
| Scheduler (Phase 6) | Fires a slot, catches up a missed slot after a restart, refreshes the lock | No. It asks the orchestrator. |
| Orchestrator | Orders the steps and commits each artifact | Yes. It is the only writer. |
| News research | Reads configured RSS or Atom feeds and returns articles | No. `discover` persists the result. |
| News selection | Scores open events and returns the ordered list | No. `discover` inserts the missing `event_selections` rows. |
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

Five checks, applied in this order. Fail-closed deduplication treats an uncertain same-language gray zone as one event. It does not merge every uncertain cross-language pair. Missing a reel is acceptable. Repeating one is not.

1. **Canonical URL.** Scheme and host are lowercased, `www` is removed, the fragment is dropped, tracking parameters (`utm_*`, `fbclid`, `gclid`, and a short list of campaign ids) are dropped, the remaining query is sorted, and a trailing slash is removed. The database unique key is `(client_id, canonical_url)`. This check is already enforced on write.
2. **Normalized headline.** Lowercase, punctuation folded, and a trailing outlet name such as “BBC News” removed. The fingerprint is a hash of the sorted significant tokens, so word order alone does not create a new story. A place name after a hyphen is kept, so “Election results - France” and “Election results - Germany” stay distinct.
3. **Same-language overlap.** Title fingerprints, token overlap, entity-and-summary overlap, and SimHash. A gray-zone pair asks the judge. Fail-closed applies only to that same-language gray zone. Conflicting proper names, such as France and Germany, stay separate. The full rules and the cross-language limits are in `docs/deduplication.md`.
4. **Cross-language hint.** With `TRANSLATION_PROVIDER=none`, two languages match only when they share an alias-catalog entity and a normalized number or the same proper token. Conflicting numbers block the match. This is not reliable multilingual deduplication. A future translator implements `Translator.translate` and then the same-language rules run on the pivot text.
5. **Related-event rule.** A new article about an event that already has a reel is stored as an update. It does not become another selection, even when the development is important.

The shipped judge always returns `uncertain`. Embeddings have a column reserved for a later provider. They are not computed.

## Daily selection

`event_selections` is append-only. `UNIQUE (client_id, event_id)` blocks a second selection of the same event on any date. `UNIQUE (client_id, production_date, rank)` blocks two stories at the same rank. The rank check allows 1 through 24 because that is the maximum of `DAILY_REEL_LIMIT`. The fill stops at the configured limit, which defaults to 3 and does not read the production slot list.

The fill runs in `BEGIN IMMEDIATE`. If the day already has enough rows, it returns them. Otherwise it inserts the next free ranks from events that are still `DISCOVERED`, have no `generated_content` row, and were never selected. A unique conflict rolls back and retries from a fresh read. Stored rows are not updated.

This table is not a production reservation. Slot reservation and video generation stay on `daily_production` and `generated_content`, and Phase 2 does not write those tables.

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
| News | RSS and Atom from `NEWS_SOURCES` or `NEWS_SOURCES_FILE`. No default feeds. | A paid API can sit behind the same fetch method. | $0 for public RSS |
| Script | Extractive English fallback copies source sentences and refuses new numbers. Phase 3 adds grounded Persian `story_package.json` via `REEL_SCRIPT_PROVIDER=openai` (mockable transport; key from `OPENAI_API_KEY`). | Same Chat Completions adapter with a stronger model. | About $0.001–0.01 per reel on a mini model, or $0 with an injected mock |
| Images | Solid PPM frame. News cards must not invent a photograph of an event. | Typographic cards via Pillow, or a sourced photo. Generative images stay optional because they can fabricate scenes. | $0 for cards. Generative images are often $0.02–$0.08 each. |
| Voice | Silent WAV sized from the word count remains for the older offline path. Phase 4 wires ElevenLabs Aran through the existing `persian-tts` client; live HTTP needs `REEL_ELEVENLABS_APPROVED` plus `ELEVENLABS_API_KEY`. | Same adapter with Edge Farid fallback when the key is unset outside the Reel pipeline. | About $0.08 per 1,000 characters on `eleven_v4` |
| Video | Encoder probe remains. Phase 5 renders Persian DataReels through the existing Remotion POC (`render-reel` / `render_with_remotion`), validated with ffprobe at 1080×1920 H.264/AAC. | FFmpeg mux/encode remains available beside Remotion. | $0 local encode; Remotion company automation pricing is separate |
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

SQLite in WAL mode, with foreign keys and a migration table. `NewsReelsRepository` is the boundary a PostgreSQL implementation can replace. Migrations are `001_initial.sql` and `002_selection_history.sql`. The current schema version is `002`.

Tables: `clients`, `news_articles`, `news_events`, `event_selections`, `generated_content`, `daily_production`, `agent_execution_logs`, `notifications`, `app_config`, `job_locks`, `schema_migrations`.

Normal operation does not delete articles, events, selections, or finished reels. The duplicate history has to outlive the process. `app_config` is not the selection record.

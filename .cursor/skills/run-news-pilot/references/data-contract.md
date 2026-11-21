# Pilot data contract v1 (NOT the Python runtime API)

The data below is for isolated Cursor experimentation. Do not assume it matches `app/agents/` contracts. The integration architect will map the validated shape later.

## Directory
`storage/generated/pilot/<run-id>/` where `run-id` is a safe filename (`YYYYMMDD-event-shortid`), not generated automatically from untrusted URLs.

## fact_pack.json — produced by parent after research
```json
{
  "event_id": "real-selection-id-or-manual-demo-id",
  "status": "READY",
  "retrieved_at": "2026-11-19T08:00:00+01:00",
  "event_summary": "Neutral description",
  "sources": [{"publisher": "Publisher", "url": "https://publisher.example/story", "published_at": "2026-11-19T07:00:00+01:00"}],
  "verified_facts": [{"text": "One checkable claim", "source_urls": ["https://publisher.example/story"]}],
  "uncertainties": [],
  "duplicate_risk": "none known"
}
```
The URLs above are placeholders illustrating the schema; never claim they are real verified news.

## editorial_review.json — produced by parent after editorial agent
```json
{"event_id": "same-id", "decision": "APPROVE", "rationale": "Evidence-based justification", "limitations": [], "audience_relevance": {"affected_audience": "who in Germany", "practical_relevance": "what changes for them", "evidence_urls": ["https://publisher.example/story"], "publication_reason": "why this is worth a Reel"}}
```
`evidence_urls` must already appear in the fact pack. A borderline story is not approved without this object.

## story_package.json — written by reel-scriptwriter
Mandatory keys:
- `schema_version`: `"pilot-1"`
- `event_id`: non-empty string, unchanged from fact pack
- `language`: e.g. `"fa-IR"`, `"en"`; parent picks the language
- `audience`: non-empty text
- `headline`: factually grounded, non-empty
- `source_urls`: one or more real URLs used in the narrative
- `claims`: each `{ "text": "...", "source_urls": ["..."] }`, where URLs appear in top-level `source_urls`
- `duration_seconds`: number > 0. A Persian report aims at 35–45 seconds. `duration_policy` may be `completeness` when a sourced script is kept even though it is outside that aim.
- `scenes`: three to eight objects, numbered from 1, each with `duration_seconds` > 0, `narration` non-empty, `on_screen_text` non-empty, `visual_prompt` non-empty. Durations sum to `duration_seconds` within 0.25s.
- `disclaimers`: array of strings (possibly empty); add attribution to synthetic news imagery in presentation plan
No claims are implicitly verified just because this JSON validates.

## visual_plan.json — written by reel-producer
`schema_version`, `event_id`, `width` = 1080, `height` = 1920, `fps` = 30, `scenes`: one item per script scene, with `{number, duration_seconds, format, fact, motion, text_placement, asset_path}`. An empty `asset_path` means *not generated*, not success. Audio metadata must distinguish actual recording/TTS from absent or mock.

## qa_report.json — optional, from parent after verifier
Report individual `facts`, `script`, `storyboard`, `audio`, `video` = `PASS | FAIL | BLOCKED | NOT_RUN`, plus reasons and checked file paths. Never use one overall PASS if video/audio were not inspected.

## Handoff safety
Keep evidence IDs/URLs intact across stages. Do not silently substitute a different news event. No code integration until explicit user approval and runtime tests.

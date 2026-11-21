# Narration Quality & Engagement Review

Production gate between Persian script generation and photograph retrieval.

## Pipeline order

1. Select story (AI editorial ranking or keyword filter)
2. Verify source / build fact pack
3. Generate Persian `story_package`
4. Structural + factual validation
5. **Narration quality review** (OpenAI structured output)
6. Optional **one** engagement rewrite + revalidation
7. Final review (second pass only when a rewrite ran)
8. Approve → photos → ElevenLabs Aran → Remotion → QA → queue

Reject stops before photos, ElevenLabs, Remotion, and Instagram.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `REEL_NARRATION_REVIEW_PROVIDER` | `off` | Set `openai` to use Chat Completions. |
| `REEL_NARRATION_REVIEW_ENABLED` | `false` | Master switch for `generate-reel` / `--scheduled`. |
| `REEL_NARRATION_REVIEW_MIN_SCORE` | `80` | Minimum mean score across dimensions. |
| `REEL_NARRATION_HOOK_MIN_SCORE` | `80` | Minimum hook score. |
| `REEL_NARRATION_CURIOSITY_MIN_SCORE` | `75` | Minimum curiosity/retention score. |
| `REEL_NARRATION_MAX_REWRITES` | `1` | Hard cap (never unbounded). |
| `REEL_NARRATION_GLOSSARY_FILE` | `config/german_term_glossary.json` | Misleading-term checks. |

Uses `OPENAI_API_KEY` / `OPENAI_SCRIPT_MODEL` unless a completer is injected in tests.

## Decision rule (Python)

The model’s `approved` field is ignored as authority. Approval requires:

- zero factual errors (model + glossary + claim grounding + spoken-length floor)
- overall score ≥ configured minimum
- hook ≥ configured minimum
- curiosity ≥ configured minimum

Maximum paid LLM traffic for this stage: **2 reviews + 1 rewrite** (schema-correction retries for the story package stay separately bounded in `persian_script`).

## Artifacts

Per event under `REEL_SCRIPT_OUTPUT_DIR/<event_id>/`:

- `story_package.json` (final approved package)
- `story_package.original.json` (pre-rewrite draft when review ran)
- `narration_review.json` (scores, issues, call counts, USD estimate)

## Spoken length

Scripts aim for ~35–45 seconds of Aran speech (~12 Persian characters/second). Drafts under ~32s are treated as quality failures and may be rewritten once.

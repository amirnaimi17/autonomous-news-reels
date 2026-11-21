---
name: reel-cost-tracking
description: Estimate Reel provider cost, reject plans over the configured budget, and append a ledger outside the news database. Use before reel-producer calls a paid voice or image provider. An estimate is not a bill.
---

# Reel cost tracking

`reel-producer` runs this before any paid request. The ledger is `storage/cost-ledger/usage.jsonl`. It is not the Phase 2 SQLite database.

## Targets

These are targets, not measured bills.

| Phase | Per Reel | 120 Reels |
| --- | --- | --- |
| Quality-first | $0.50 | $60 |
| Optimization | $0.25 | $30 |
| Scale | $0.10 | $12 |

The active cap is `config/budget.json`: $0.50 per Reel and $60 per month.

## Rules

- Price from `config/pricing.json`. Each entry has currency USD, a unit, an effective date, and a source URL or a local observation.
- A missing price, an incomplete token quote, or an unverified Remotion license blocks the Reel.
- `gpt-image-2.5-sunburst` at `1024x1536` and quality `high` has a documented calculator estimate of 1372 image-output tokens, or $0.04116. That estimate excludes text input and is not a spending ceiling. A quote without text and image input tokens stays blocked. Measured `usage` replaces the estimate after a call.
- The Reel cap stays $0.50. A priced ElevenLabs voice test is authorized on its own. An OpenAI image with unknown output tokens stays blocked and does not veto the voice test. `scripts/prepare_api_test.py` writes both decisions.
- Cursor GenerateImage has no published price here, so a new Cursor image cannot pass the gate.
- Cache hits cost $0. More than two attempts is rejected.
- Edge TTS and local FFmpeg are recorded as unbilled, not as a guaranteed free commercial license.
- Do not describe an estimate as the amount the provider charged.

```bash
python3 .cursor/skills/reel-cost-tracking/tests/test_costing.py
python3 .cursor/skills/reel-cost-tracking/scripts/estimate_reel.py \
  --plan storage/cost-ledger/plan.json \
  --ledger storage/cost-ledger/usage.jsonl \
  --month 2026-11
```

Credentials come from the process environment: `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`. Put them in an untracked `.env` with mode `600`, then export them into the shell that runs the test. `.env` is gitignored. Do not print, log, or commit the values, and do not store them in SQLite or a story JSON file. The skill scripts do not load `.env` by themselves. None of these variables is set in this environment.

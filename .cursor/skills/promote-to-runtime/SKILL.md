---
name: promote-to-runtime
description: Map one approved and tested Cursor news-Reel pilot step onto existing Python provider contracts and integration tests; require a second explicit approval before code changes.
disable-model-invocation: true
---
# Promote a proven pilot step into Python

This is a proposal-only skill until the user separately authorizes implementation.

1. Require pilot artifacts, `qa-verifier` results and a named step (research, selection, script, image, voice or render).
2. Inspect existing real signatures/contracts in `app/agents/`, `app/services/`, `app/orchestrator/`, `app/database/`. Do not invent class names or rewrite the already-working Phase 1–2 architecture.
3. Design a minimal adapter/provider which works outside Cursor on a VPS. A Cursor agent definition is not itself a callable background service.
4. Define structured inputs/outputs, provider/model configuration, credential isolation, idempotency, retries, timestamps, failure recovery and exact test fixtures.
5. Do not change Phase 2 `event_selections`, event lifecycle, concurrency, client isolation, or quota. Keep orchestrator as sole coordinator of production.
6. State estimated API/GPU usage, offline fallback, observability and deployment implications.
7. Present file-by-file implementation plan and acceptance tests; stop and await explicit approval before editing code, running migrations or deploying.

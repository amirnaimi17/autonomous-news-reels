---
name: reel-quality-assurance
description: Run automated technical checks on a rendered Reel and write a contact sheet. Use after reel-video-design, from qa-verifier or /run-news-pilot. A technical pass is not human approval of the voice or the design.
---

# Reel quality assurance

`qa-verifier` runs this after `verify-reel-pilot`. It does not replace the factual audit.

Checks: resolution 1080×1920, about 30 fps, H.264, duration window, AAC audio, peak below −0.5 dB, mean loudness above silence, no black stretch of 0.2s, four image files, narration from Aran at speed 1.0 or Farid at `+0%`, and a four-frame contact sheet.

```bash
python3 .cursor/skills/reel-quality-assurance/scripts/check_reel.py \
  --video storage/generated/pilot/<run-id>/reel.mp4 \
  --manifest storage/generated/pilot/<run-id>/audio/voice_manifest.json \
  --images storage/generated/pilot/<run-id>/scene-01.jpg \
    storage/generated/pilot/<run-id>/scene-02.jpg \
    storage/generated/pilot/<run-id>/scene-03.jpg \
    storage/generated/pilot/<run-id>/scene-04.jpg \
  --out storage/generated/pilot/<run-id>/qa_technical.json
python3 .cursor/skills/reel-quality-assurance/tests/test_check_reel.py
```

`technical_pass: true` only means the measurements above matched. `human_review.voice_naturalness` and `human_review.design_quality` stay `not reviewed` until a person listens and looks.

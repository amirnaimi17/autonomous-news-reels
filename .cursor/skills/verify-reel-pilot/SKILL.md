---
name: verify-reel-pilot
description: Audit a pilot Reel's source-backed facts, JSON shape, storyboard, audio, and rendered video separately; refuse to label an unrun stage PASS.
---
# Verify pilot outputs

Run this skill independently using `qa-verifier`.

## Structural check
```
python3 .cursor/skills/verify-reel-pilot/scripts/validate_story_package.py storage/generated/pilot/<run-id>/story_package.json
```
An absent file is `NOT_RUN`. A JSON schema pass is **not** a factual pass.

## Factual check
Compare all `claims` against source contents and timestamps, not merely URLs. Any unsupported figure, quote or causal statement blocks public release.

## Storyboard check
Four 1080x1920 scene plans, timings matching story package, safe/readable captions, accurate illustration labels, Persian RTL preview where applicable.

## Voice check
If `audio/voice_manifest.json` exists, `engine` must be `edge-tts`, `voice` must be `fa-IR-FaridNeural` unless the user chose another Edge voice, and `espeak_used` must be false. A manifest does not prove pronunciation. Mark audio BLOCKED for intelligibility until a person has listened.

## Video check (only if MP4 exists)
```
ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt -show_entries format=duration -of json storage/generated/pilot/<run-id>/draft.mp4
```
Inspect real images/screenshots and listen to actual audio; `ffprobe` alone cannot prove quality. A silent or placeholder track is NOT completed narration. Ensure no publishing occurred.

## Verdict
Return five independent statuses: `facts`, `script`, `storyboard`, `audio`, `video`: `PASS | FAIL | BLOCKED | NOT_RUN`. Include exact commands and observed evidence, not predicted output. Don't approve production integration merely because the sample looks good.

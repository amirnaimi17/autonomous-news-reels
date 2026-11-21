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
```
python3 .cursor/skills/verify-reel-pilot/scripts/validate_visual_plan.py storage/generated/pilot/<run-id>/visual_plan.json
```
The scene count follows the script. A generated-image scene needs a complete English prompt with navy, yellow, and white, and no Persian type. Charts, maps, and timelines do not need an image prompt. Persian type belongs in Remotion.

## Voice check
If `audio/voice_manifest.json` exists, accept ElevenLabs Aran (`eleven_v4`, voice `PEdcOLzbXYhL8IKOswXB`, language `fa`, speed `1.0`) or Edge Farid at `+0%`. `espeak_used` must be false. Timestamps must belong to that recording. A manifest does not prove pronunciation. Mark audio BLOCKED for intelligibility until a person has listened. Also run `reel-quality-assurance` for the technical probe and contact sheet.

## Video check (only if MP4 exists)
```
ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt -show_entries format=duration -of json storage/generated/pilot/<run-id>/draft.mp4
```
Inspect real images/screenshots and listen to actual audio; `ffprobe` alone cannot prove quality. A silent or placeholder track is NOT completed narration. Ensure no publishing occurred.

## Verdict
Return five independent statuses: `facts`, `script`, `storyboard`, `audio`, `video`: `PASS | FAIL | BLOCKED | NOT_RUN`. Include exact commands and observed evidence, not predicted output. Don't approve production integration merely because the sample looks good.

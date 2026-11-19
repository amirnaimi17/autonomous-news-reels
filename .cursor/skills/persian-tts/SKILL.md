---
name: persian-tts
description: Generate reusable Persian Reel narration with Microsoft Edge TTS voice fa-IR-FaridNeural, natural news pacing, and a duration that matches the video. Use when a pilot needs Persian speech, Farid, fa-IR narration, or a voice track for /run-news-pilot. Never use espeak-ng.
---

# Persian TTS

Use this for every fa-IR Reel narration. The voice generator is the existing `reel-producer`, not a second agent.

## Rules

- Engine: Microsoft Edge TTS (`edge-tts`). Default voice: `fa-IR-FaridNeural`.
- Never use `espeak-ng`, a silent WAV, or another voice unless the user names one for a listening test.
- Write narration as spoken news copy: short sentences, professional and conversational, not a headline shouted aloud.
- Start at rate `+0%`, pitch `+0Hz`. The script may change only the rate, between `-15%` and `+30%`, so the finished video lands in the requested window.
- Default window is 38–42 seconds after the 0.4s scene transitions. Pass a different window only when the user set one.
- Save `voice_manifest.json` next to the scene mp3 files. It must record `engine`, `voice`, `rate`, and `espeak_used: false`.

## Setup

```bash
python3 -m venv .cursor/skills/persian-tts/.venv
.cursor/skills/persian-tts/.venv/bin/pip install -r .cursor/skills/persian-tts/requirements.txt
```

## Generate

```bash
.cursor/skills/persian-tts/.venv/bin/python .cursor/skills/persian-tts/scripts/speak.py \
  --story storage/generated/pilot/<run-id>/story_package.json \
  --out-dir storage/generated/pilot/<run-id>/audio \
  --voice fa-IR-FaridNeural --rate +0% --target 40 --min-seconds 38 --max-seconds 42 --transition 0.4
```

The script reads the four `narration` strings, writes `scene-01.mp3` through `scene-04.mp3` plus word timings, and retries the rate until the estimated final duration fits. If it cannot fit without leaving that rate band, it stops. Do not pad with espeak or time-stretch.

Do not generate the MP4 from this skill. Hand `audio/voice_manifest.json` to `reel-video-design`.

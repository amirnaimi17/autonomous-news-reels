---
name: reel-video-design
description: Render a four-scene 1080x1920 Instagram Reel with timed Persian subtitles, scene transitions, and NVENC H.264. Use when /run-news-pilot or reel-producer builds the MP4 after persian-tts. Do not use this to invent narration.
---

# Reel video design

The existing `reel-producer` runs this after `persian-tts`. Do not add a second video agent.

A two-second Remotion 4.0.545 proof rendered locally: `storage/generated/pilot/20261119-07300041-remotion-poc/card.mp4` is 1080×1920, H.264, 30 fps, and 2.000 seconds. The still is `frame.png`. It uses Vazirmatn, RTL type, and two animated bars. It has no narration and it is not a Reel. The production renderer remains FFmpeg.

Node.js 22.21.1 is installed under `.cursor/skills/reel-video-design/.tools/` and is not on the system path. The published Remotion pricing page, retrieved 2026-11-19, allows free use for an individual or an organization of up to 3 people, and prices company automation at $0.01 per render with a $100 monthly minimum. That minimum is above the $60 monthly target. This project's headcount was not verified, and the installed package is 4.0.545 while the v5 terms are described as taking effect at version 5.0. Do not treat the proof as a licensed production render.

## Picture

- 1080×1920, 30 fps, H.264 AAC. The scene count and duration follow the approved script.
- Remotion sets the Persian type, maps, charts, and timelines. FFmpeg can still encode or mux. Do not present a graphic as a photograph of the event.
- One shared look: darkened illustrations, the same Persian type, a persistent disclaimer that the images are drawings.
- Motion is a slow drift and scale that changes per scene, then `smoothleft`, `smoothright`, and `fade` transitions of 0.4s. Do not use a single static zoom with hard cuts.
- Headlines are the short `on_screen_text` lines. Subtitles are the spoken narration, timed from Edge word boundaries, shaped with Vazirmatn through libass. Do not use `drawtext` for Persian.
- Prefer `h264_nvenc` when a one-frame encode succeeds. If it fails, use `libx264` and say so. Do not claim NVENC from the encoder list alone.
- Illustrations stay illustrations. Do not present them as photographs of the people or the event.

## Render

Requires `audio/voice_manifest.json` from `persian-tts`. The production voice is ElevenLabs Aran at speed 1.0. Edge Farid at `+0%` remains acceptable.

```bash
python3 .cursor/skills/reel-video-design/scripts/render_reel.py \
  --story storage/generated/pilot/<run-id>/story_package.json \
  --manifest storage/generated/pilot/<run-id>/audio/voice_manifest.json \
  --images scene-01.jpg scene-02.jpg scene-03.jpg scene-04.jpg \
  --work storage/generated/pilot/<run-id>/work \
  --out storage/generated/pilot/<run-id>/reel.mp4
```

Then `ffprobe` the MP4 and read `render_report.json`. Update `story_package.json` scene durations so they sum to the measured duration within 0.25s. A file that does not decode is not a finished Reel.
